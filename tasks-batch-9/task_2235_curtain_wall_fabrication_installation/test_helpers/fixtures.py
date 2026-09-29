"""Composite setup helpers.

Every test starts against an empty store, so all state is built here from the
service's own endpoints. Helpers accumulate their results in a plain `ctx`
dictionary that later helpers read, so a test can stop the chain at any point
and inspect what has been built so far.

`ctx` keys
----------
package, package_id        the facade package row and its id
lab, lab_id                the accredited laboratory
mockups                    every mockup test booked, in booking order
mockup, mockup_id          the most recent mockup test
submittal, submittal_id    the most recent shop drawing submittal
submittals                 every submittal created, in creation order
glass_order, glass_order_id
zones                      every installation zone, in creation order
zone_ids                   the zone ids, in creation order
release, release_id        the most recent fabrication release
releases                   every fabrication release, in creation order
lots                       zone_id -> list of that zone's panel lots
surveys                    zone_id -> that zone's embed survey row
rig, rig_id                the hoist rig
reservations               zone_id -> that zone's most recent reservation
crew_days                  zone_id -> list of posted crew day logs
field_tests                zone_id -> list of field test rows
defects                    every defect item raised, in creation order
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_FIELD_TEST_DAY,
    CLOCK_HANG_DAY,
    CLOCK_T0,
    CLOCK_ZONE_B_HANG,
    USER_IDS,
    ZONE_A_CREW_DAYS,
    ZONE_B_CREW_DAYS,
)
from . import factories as f
from .test_users import (
    make_architect_of_record_headers,
    make_delegated_engineer_headers,
    make_field_superintendent_headers,
    make_qc_inspector_headers,
    make_structural_contractor_headers,
    TEST_USERS,
)

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
ENGINEER = TEST_USERS["delegated_engineer_headers"]
ARCHITECT = TEST_USERS["architect_of_record_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


def new_ctx() -> dict:
    return {
        "mockups": [],
        "submittals": [],
        "zones": [],
        "zone_ids": [],
        "releases": [],
        "lots": {},
        "surveys": {},
        "reservations": {},
        "crew_days": {},
        "field_tests": {},
        "defects": [],
    }


# ---------------------------------------------------------------------------
# Atomic steps
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Move the logical project clock."""
    return get_success_data(api_client.set_current_utc(f.set_clock_payload(to_iso8601)))


def create_package(ctx: dict, **overrides) -> dict:
    ctx["package"] = get_success_data(
        api_client.create_facade_package(
            f.create_facade_package_payload(**overrides), PM
        )
    )
    ctx["package_id"] = ctx["package"]["id"]
    return ctx["package"]


def decide_system(ctx: dict, system_type: str = "UNITIZED") -> dict:
    ctx["package"] = get_success_data(
        api_client.decide_system(
            ctx["package_id"], f.system_decision_payload(system_type), PM
        )
    )
    return ctx["package"]


def refresh_package(ctx: dict) -> dict:
    ctx["package"] = get_success_data(
        api_client.get_facade_package(ctx["package_id"], PM)
    )
    return ctx["package"]


def package_version(ctx: dict) -> int:
    """Read the package's current version, as the release call must echo it."""
    return refresh_package(ctx)["version"]


def create_lab(ctx: dict, **overrides) -> dict:
    ctx["lab"] = get_success_data(
        api_client.create_test_lab(f.create_test_lab_payload(**overrides), PM)
    )
    ctx["lab_id"] = ctx["lab"]["id"]
    return ctx["lab"]


def book_mockup(ctx: dict, **overrides) -> dict:
    mockup = get_success_data(
        api_client.create_mockup_test(
            f.create_mockup_test_payload(ctx["package_id"], ctx["lab_id"], **overrides),
            PM,
        )
    )
    ctx["mockups"].append(mockup)
    ctx["mockup"] = mockup
    ctx["mockup_id"] = mockup["id"]
    return mockup


def record_mockup_result(ctx: dict, mockup_id: str = None, user_id: str = None, **overrides):
    headers = make_qc_inspector_headers(user_id or USER_IDS["QC_1"])
    mockup = get_success_data(
        api_client.record_mockup_result(
            mockup_id or ctx["mockup_id"], f.record_mockup_result_payload(**overrides), headers
        )
    )
    ctx["mockup"] = mockup
    return mockup


def create_submittal(ctx: dict, **overrides) -> dict:
    submittal = get_success_data(
        api_client.create_submittal(
            f.create_submittal_payload(ctx["package_id"], **overrides), DETAILER
        )
    )
    ctx["submittals"].append(submittal)
    ctx["submittal"] = submittal
    ctx["submittal_id"] = submittal["id"]
    return submittal


def seal_submittal(ctx: dict, submittal_id: str = None, user_id: str = None, **overrides):
    headers = make_delegated_engineer_headers(user_id or USER_IDS["ENGINEER"])
    submittal = get_success_data(
        api_client.seal_submittal(
            submittal_id or ctx["submittal_id"], f.seal_payload(**overrides), headers
        )
    )
    ctx["submittal"] = submittal
    return submittal


def start_review(ctx: dict, submittal_id: str = None, user_id: str = None):
    headers = make_architect_of_record_headers(user_id or USER_IDS["ARCHITECT"])
    submittal = get_success_data(
        api_client.start_submittal_review(
            submittal_id or ctx["submittal_id"], f.start_review_payload(), headers
        )
    )
    ctx["submittal"] = submittal
    return submittal


def review_submittal(
    ctx: dict, decision: str, submittal_id: str = None, user_id: str = None, **overrides
):
    headers = make_architect_of_record_headers(user_id or USER_IDS["ARCHITECT"])
    submittal = get_success_data(
        api_client.review_submittal(
            submittal_id or ctx["submittal_id"],
            f.review_payload(decision, **overrides),
            headers,
        )
    )
    ctx["submittal"] = submittal
    return submittal


def resubmit_submittal(ctx: dict, drawing_set_ref: str, submittal_id: str = None, **overrides):
    submittal = get_success_data(
        api_client.resubmit_submittal(
            submittal_id or ctx["submittal_id"],
            f.resubmit_payload(drawing_set_ref, **overrides),
            DETAILER,
        )
    )
    ctx["submittal"] = submittal
    return submittal


def create_glass_order(ctx: dict, **overrides) -> dict:
    ctx["glass_order"] = get_success_data(
        api_client.create_glass_order(
            f.create_glass_order_payload(ctx["package_id"], **overrides), PROCUREMENT
        )
    )
    ctx["glass_order_id"] = ctx["glass_order"]["id"]
    return ctx["glass_order"]


def start_glass_production(ctx: dict) -> dict:
    ctx["glass_order"] = get_success_data(
        api_client.start_glass_production(
            ctx["glass_order_id"], f.start_production_payload(), PROCUREMENT
        )
    )
    return ctx["glass_order"]


def receive_glass(ctx: dict, received_lites: int) -> dict:
    ctx["glass_order"] = get_success_data(
        api_client.receive_glass_order(
            ctx["glass_order_id"], f.receive_payload(received_lites), PROCUREMENT
        )
    )
    return ctx["glass_order"]


def refresh_glass_order(ctx: dict) -> dict:
    ctx["glass_order"] = get_success_data(
        api_client.get_glass_order(ctx["glass_order_id"], PROCUREMENT)
    )
    return ctx["glass_order"]


def create_zone(ctx: dict, payload_builder=None, **overrides) -> dict:
    builder = payload_builder or f.create_installation_zone_payload
    zone = get_success_data(
        api_client.create_installation_zone(builder(ctx["package_id"], **overrides), PM)
    )
    ctx["zones"].append(zone)
    ctx["zone_ids"].append(zone["id"])
    return zone


def refresh_zone(ctx: dict, zone_id: str) -> dict:
    zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
    for index, existing in enumerate(ctx["zones"]):
        if existing["id"] == zone_id:
            ctx["zones"][index] = zone
    return zone


def create_release(
    ctx: dict, zone_ids=None, panels_per_zone: int = 36, lites_per_panel: int = 2, **overrides
) -> dict:
    payload = f.create_fabrication_release_payload(
        ctx["package_id"],
        ctx["submittal_id"],
        ctx["glass_order_id"],
        zone_ids if zone_ids is not None else list(ctx["zone_ids"]),
        overrides.pop("expected_package_version", package_version(ctx)),
        panels_per_zone=panels_per_zone,
        lites_per_panel=lites_per_panel,
        **overrides,
    )
    release = get_success_data(api_client.create_fabrication_release(payload, PM))
    ctx["releases"].append(release)
    ctx["release"] = release
    ctx["release_id"] = release["id"]
    for zone_id in payload["zone_ids"]:
        ctx["lots"].setdefault(zone_id, [])
        ctx["lots"][zone_id].extend(load_lots_for_zone(ctx, zone_id, release["id"]))
    return release


def load_lots_for_zone(ctx: dict, zone_id: str, release_id: str = None) -> list:
    """The lots the service minted for one zone under one release."""
    params = {"zone_id": zone_id}
    if release_id:
        params["release_id"] = release_id
    body = api_client.list_panel_lots(PM, params=params)
    return get_success_data(body) or []


def advance_lot(ctx: dict, lot_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.advance_fabrication(
            lot_id, f.advance_fabrication_payload(to_status), SUPERINTENDENT
        )
    )


def ship_zone_lots(ctx: dict, zone_id: str) -> list:
    """Walk every lot of one zone from BATCHED through GLAZED to SHIPPED."""
    shipped = []
    for lot in ctx["lots"].get(zone_id, []):
        advance_lot(ctx, lot["id"], "GLAZED")
        shipped.append(advance_lot(ctx, lot["id"], "SHIPPED"))
    return shipped


def glaze_zone_lots(ctx: dict, zone_id: str) -> list:
    return [advance_lot(ctx, lot["id"], "GLAZED") for lot in ctx["lots"].get(zone_id, [])]


def open_embed_survey(ctx: dict, zone_id: str, **overrides) -> dict:
    survey = get_success_data(
        api_client.create_embed_survey(
            zone_id, f.create_embed_survey_payload(**overrides), STRUCTURAL
        )
    )
    ctx["surveys"][zone_id] = survey
    return survey


def record_survey(ctx: dict, zone_id: str, user_id: str = None, **overrides) -> dict:
    headers = make_structural_contractor_headers(user_id or USER_IDS["STRUCTURAL"])
    survey = get_success_data(
        api_client.record_embed_survey(
            ctx["surveys"][zone_id]["id"], f.record_survey_payload(**overrides), headers
        )
    )
    ctx["surveys"][zone_id] = survey
    return survey


def confirm_pour(ctx: dict, zone_id: str, poured_at: str) -> dict:
    survey = get_success_data(
        api_client.confirm_pour(
            ctx["surveys"][zone_id]["id"], f.confirm_pour_payload(poured_at), STRUCTURAL
        )
    )
    ctx["surveys"][zone_id] = survey
    return survey


def set_anchors(ctx: dict, zone_id: str) -> dict:
    return get_success_data(
        api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT)
    )


def create_rig(ctx: dict, **overrides) -> dict:
    ctx["rig"] = get_success_data(
        api_client.create_hoist_rig(
            f.create_hoist_rig_payload(ctx["package_id"], **overrides), SUPERINTENDENT
        )
    )
    ctx["rig_id"] = ctx["rig"]["id"]
    return ctx["rig"]


def create_reservation(
    ctx: dict, zone_id: str, window_start: str, window_end: str, **overrides
) -> dict:
    reservation = get_success_data(
        api_client.create_hoist_reservation(
            f.create_hoist_reservation_payload(
                ctx["rig_id"], zone_id, window_start, window_end, **overrides
            ),
            SUPERINTENDENT,
        )
    )
    ctx["reservations"][zone_id] = reservation
    return reservation


def hang_panels(ctx: dict, zone_id: str, reservation_id: str = None) -> dict:
    reservation_id = reservation_id or ctx["reservations"][zone_id]["id"]
    return get_success_data(
        api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
    )


def post_crew_day(ctx: dict, zone_id: str, user_id: str = None, **day) -> dict:
    headers = make_field_superintendent_headers(user_id or USER_IDS["SUPERINTENDENT"])
    log = get_success_data(
        api_client.post_crew_day(zone_id, f.create_crew_day_payload(**day), headers)
    )
    ctx["crew_days"].setdefault(zone_id, []).append(log)
    return log


def post_crew_days(ctx: dict, zone_id: str, days: list) -> list:
    return [post_crew_day(ctx, zone_id, **day) for day in days]


def schedule_field_test(ctx: dict, zone_id: str, test_kind: str, scheduled_for: str, **overrides):
    test = get_success_data(
        api_client.schedule_field_test(
            zone_id, f.schedule_field_test_payload(test_kind, scheduled_for, **overrides), QC
        )
    )
    ctx["field_tests"].setdefault(zone_id, []).append(test)
    return test


def record_field_test(ctx: dict, test_id: str, payload: dict, user_id: str = None) -> dict:
    headers = make_qc_inspector_headers(user_id or USER_IDS["QC_2"])
    return get_success_data(api_client.record_field_test_result(test_id, payload, headers))


def certify_zone(ctx: dict, zone_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(**overrides), PM
        )
    )


def raise_defect(ctx: dict, user_id: str = None, **overrides) -> dict:
    headers = make_qc_inspector_headers(user_id or USER_IDS["QC_3"])
    defect = get_success_data(
        api_client.create_defect_item(
            f.create_defect_item_payload(ctx["package_id"], **overrides), headers
        )
    )
    ctx["defects"].append(defect)
    return defect


def submit_remediation(ctx: dict, defect_id: str, note: str = "resealed and retooled") -> dict:
    return get_success_data(
        api_client.submit_defect_remediation(
            defect_id, f.submit_remediation_payload(note), DETAILER
        )
    )


def reinspect_defect(ctx: dict, defect_id: str, outcome: str, user_id: str = None) -> dict:
    headers = make_qc_inspector_headers(user_id or USER_IDS["QC_1"])
    return get_success_data(
        api_client.reinspect_defect(defect_id, f.reinspect_payload(outcome), headers)
    )


def create_breakage_draw(
    ctx: dict, panel_lot_id: str, quantity_lites: int, reason: str = "FIELD_BREAKAGE", **overrides
) -> dict:
    version = overrides.pop(
        "expected_glass_order_version", refresh_glass_order(ctx)["version"]
    )
    return get_success_data(
        api_client.create_breakage_draw(
            f.create_breakage_draw_payload(
                ctx["glass_order_id"], panel_lot_id, quantity_lites, version,
                reason=reason, **overrides,
            ),
            PROCUREMENT,
        )
    )


# ---------------------------------------------------------------------------
# Layered scenario builders
# ---------------------------------------------------------------------------
def new_project(clock: str = CLOCK_T0, system_type: str = "UNITIZED", **package_overrides) -> dict:
    """A package on the logical clock with its system fork already taken.

    Pass system_type=None to leave the fork undecided.
    """
    ctx = new_ctx()
    set_clock(clock)
    create_package(ctx, **package_overrides)
    if system_type is not None:
        decide_system(ctx, system_type)
    return ctx


def add_qualified_mockup(ctx: dict, **overrides) -> dict:
    """A laboratory plus one passing mockup, which qualifies the package."""
    create_lab(ctx)
    book_mockup(ctx, **overrides)
    record_mockup_result(ctx)
    return ctx["mockup"]


def add_failed_mockup(ctx: dict, **overrides) -> dict:
    """A laboratory plus one mockup that leaks water, which mints a critical
    mockup defect and leaves the package unqualified."""
    create_lab(ctx)
    book_mockup(ctx, **overrides)
    record_mockup_result(ctx, water_penetration_observed=True)
    return ctx["mockup"]


def add_approved_submittal(
    ctx: dict, decision: str = "APPROVED", notes_count: int = None, **overrides
) -> dict:
    """A sealed submittal carried through review to the named decision.

    `notes_count` belongs to the review payload, not to the submittal payload:
    the PRD's `APPROVED_AS_NOTED` branch "requires the payload's `notes_count`
    to be at least 1", so it defaults to 1 on that branch and is omitted on the
    others.
    """
    create_submittal(ctx, **overrides)
    seal_submittal(ctx)
    start_review(ctx)
    review_kwargs = {}
    if notes_count is not None:
        review_kwargs["notes_count"] = notes_count
    elif decision == "APPROVED_AS_NOTED":
        review_kwargs["notes_count"] = 1
    review_submittal(ctx, decision, **review_kwargs)
    return ctx["submittal"]


def add_received_glass_order(
    ctx: dict, ordered_lites: int = 240, received_lites: int = None, **overrides
) -> dict:
    """A glass order walked from ORDERED through IN_PRODUCTION to RECEIVED."""
    create_glass_order(ctx, ordered_lites=ordered_lites, **overrides)
    start_glass_production(ctx)
    receive_glass(ctx, received_lites if received_lites is not None else ordered_lites)
    return ctx["glass_order"]


def add_zone_a(ctx: dict, **overrides) -> dict:
    return create_zone(ctx, f.create_installation_zone_payload, **overrides)


def add_zone_b(ctx: dict, **overrides) -> dict:
    return create_zone(ctx, f.zone_b_payload, **overrides)


def add_poured_embeds(
    ctx: dict, zone_id: str, poured_at: str = "2026-08-06T12:00:00Z",
    embed_layout_ref: str = None, **survey_overrides,
) -> dict:
    """An embed survey accepted on its first pass and then poured."""
    kwargs = {}
    if embed_layout_ref:
        kwargs["embed_layout_ref"] = embed_layout_ref
    open_embed_survey(ctx, zone_id, **kwargs)
    record_survey(ctx, zone_id, **survey_overrides)
    confirm_pour(ctx, zone_id, poured_at)
    return ctx["surveys"][zone_id]


def prepare_zone_for_hang(
    ctx: dict,
    zone_id: str,
    poured_at: str = "2026-08-06T12:00:00Z",
    embed_layout_ref: str = "EL-05-N",
    window_start: str = "2026-08-10T06:00:00Z",
    window_end: str = "2026-08-10T18:00:00Z",
    planned_panel_count: int = 36,
) -> dict:
    """Ship the zone's lots, accept and pour its embeds, set its anchors and
    reserve the rig — everything the hang step demands."""
    ship_zone_lots(ctx, zone_id)
    add_poured_embeds(ctx, zone_id, poured_at=poured_at, embed_layout_ref=embed_layout_ref)
    set_anchors(ctx, zone_id)
    if "rig_id" not in ctx:
        create_rig(ctx)
    create_reservation(
        ctx, zone_id, window_start, window_end, planned_panel_count=planned_panel_count
    )
    return ctx["reservations"][zone_id]


def pass_field_tests(
    ctx: dict,
    zone_id: str,
    scheduled_for: str = None,
    air_cfm: float = 0.04,
    user_id: str = None,
) -> list:
    """A passing water test and a passing air test — the two evidence kinds a
    certification demands."""
    scheduled_for = scheduled_for or CLOCK_FIELD_TEST_DAY
    water = schedule_field_test(ctx, zone_id, "WATER_AAMA_501_2", scheduled_for)
    water = record_field_test(ctx, water["id"], f.water_result_payload(False), user_id)
    air = schedule_field_test(ctx, zone_id, "AIR_INFILTRATION", scheduled_for)
    air = record_field_test(ctx, air["id"], f.air_result_payload(air_cfm), user_id)
    return [water, air]


# ---------------------------------------------------------------------------
# High-level entry points
# ---------------------------------------------------------------------------
def setup_qualified_package(system_type: str = "UNITIZED", **package_overrides) -> dict:
    """A package whose system fork is taken and whose mockup has passed."""
    ctx = new_project(system_type=system_type, **package_overrides)
    add_qualified_mockup(ctx)
    return ctx


def setup_ready_for_release(
    system_type: str = "UNITIZED",
    ordered_lites: int = 240,
    received_lites: int = None,
    zone_count: int = 1,
    **package_overrides,
) -> dict:
    """A qualified package with an approved submittal, received glass and the
    requested number of zones — the state a fabrication release requires."""
    ctx = setup_qualified_package(system_type=system_type, **package_overrides)
    add_approved_submittal(ctx)
    add_received_glass_order(ctx, ordered_lites=ordered_lites, received_lites=received_lites)
    add_zone_a(ctx)
    if zone_count > 1:
        add_zone_b(ctx)
    return ctx


def setup_released_zone(
    zone_ids=None, panels_per_zone: int = 36, lites_per_panel: int = 2, **kwargs
) -> dict:
    """One fabrication release, so every named zone owns a batched panel lot."""
    zone_count = kwargs.pop("zone_count", 1)
    ctx = setup_ready_for_release(zone_count=zone_count, **kwargs)
    create_release(
        ctx,
        zone_ids=zone_ids,
        panels_per_zone=panels_per_zone,
        lites_per_panel=lites_per_panel,
    )
    return ctx


def setup_zone_ready_to_hang(**kwargs) -> dict:
    """Zone A released, shipped, poured, anchored and reserved, with the clock
    moved into the reserved window."""
    ctx = setup_released_zone(**kwargs)
    prepare_zone_for_hang(ctx, ctx["zone_ids"][0])
    set_clock(CLOCK_HANG_DAY)
    return ctx


def setup_hung_zone(**kwargs) -> dict:
    """Zone A with its panels hung and its reservation consumed."""
    ctx = setup_zone_ready_to_hang(**kwargs)
    hang_panels(ctx, ctx["zone_ids"][0])
    return ctx


def setup_hung_zone_with_crew_days(crew_days: list = None, **kwargs) -> dict:
    """Zone A hung, with three crew days posted against it."""
    ctx = setup_hung_zone(**kwargs)
    post_crew_days(ctx, ctx["zone_ids"][0], crew_days or ZONE_A_CREW_DAYS)
    return ctx


def setup_zone_ready_to_certify(crew_days: list = None, **kwargs) -> dict:
    """Zone A hung, crew days posted, and both field tests passed — the state a
    weather tightness certification requires."""
    ctx = setup_hung_zone_with_crew_days(crew_days=crew_days, **kwargs)
    set_clock(CLOCK_FIELD_TEST_DAY)
    pass_field_tests(ctx, ctx["zone_ids"][0], user_id=USER_IDS["QC_2"])
    return ctx


def setup_certified_zone(crew_days: list = None, **kwargs) -> dict:
    """Zone A certified weather tight, so the package carries one certified
    line and its earned value."""
    ctx = setup_zone_ready_to_certify(crew_days=crew_days, **kwargs)
    certify_zone(ctx, ctx["zone_ids"][0])
    refresh_package(ctx)
    return ctx


def setup_two_certified_zones(**kwargs) -> dict:
    """Zones A and B both certified weather tight under one release, so the
    package's earned value sums two rounded lines."""
    kwargs.setdefault("ordered_lites", 240)
    ctx = setup_ready_for_release(zone_count=2, **kwargs)
    zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
    create_release(ctx, zone_ids=[zone_a, zone_b])

    prepare_zone_for_hang(ctx, zone_a)
    set_clock(CLOCK_HANG_DAY)
    hang_panels(ctx, zone_a)
    post_crew_days(ctx, zone_a, ZONE_A_CREW_DAYS)

    prepare_zone_for_hang(
        ctx,
        zone_b,
        poured_at="2026-08-07T12:00:00Z",
        embed_layout_ref="EL-06-N",
        window_start="2026-08-11T06:00:00Z",
        window_end="2026-08-11T18:00:00Z",
    )
    set_clock(CLOCK_ZONE_B_HANG)
    hang_panels(ctx, zone_b)
    post_crew_days(ctx, zone_b, ZONE_B_CREW_DAYS)

    set_clock(CLOCK_FIELD_TEST_DAY)
    pass_field_tests(ctx, zone_a, user_id=USER_IDS["QC_2"])
    certify_zone(ctx, zone_a)
    pass_field_tests(ctx, zone_b, user_id=USER_IDS["QC_2"])
    certify_zone(ctx, zone_b)
    refresh_package(ctx)
    return ctx


def setup_escalated_submittal(**kwargs) -> dict:
    """A submittal driven through two revision rounds so that the third review
    escalates it, freezing the package."""
    ctx = new_project(**kwargs)
    create_submittal(ctx)
    seal_submittal(ctx)
    start_review(ctx)
    review_submittal(ctx, "REVISION_REQUIRED")
    resubmit_submittal(ctx, "SD-002")
    seal_submittal(ctx)
    start_review(ctx)
    review_submittal(ctx, "REVISION_REQUIRED")
    resubmit_submittal(ctx, "SD-003")
    seal_submittal(ctx)
    start_review(ctx)
    review_submittal(ctx, "REVISION_REQUIRED")
    refresh_package(ctx)
    return ctx


def setup_approved_as_noted_submittal(notes_count: int = 2, **kwargs) -> dict:
    """A qualified package whose submittal was approved as noted, leaving open
    review notes on the row."""
    ctx = setup_qualified_package(**kwargs)
    add_approved_submittal(ctx, decision="APPROVED_AS_NOTED", notes_count=notes_count)
    return ctx


def setup_open_critical_defect(ctx: dict, user_id: str = None) -> dict:
    """A critical punch list defect, which restricts the package."""
    defect = raise_defect(ctx, user_id=user_id, severity="CRITICAL")
    refresh_package(ctx)
    return defect


def setup_glass_order_with_breakage_stock(
    ordered_lites: int = 240, received_lites: int = None, **kwargs
) -> dict:
    """A released zone whose glass order carries a breakage reserve, so draws
    can be taken against its lot."""
    ctx = setup_released_zone(ordered_lites=ordered_lites, received_lites=received_lites, **kwargs)
    refresh_glass_order(ctx)
    return ctx


def setup_lab_with_capacity(chamber_capacity: int = 2, **kwargs) -> dict:
    """A package plus a laboratory of the named chamber capacity, for the
    booking-overlap scenarios."""
    ctx = new_project(**kwargs)
    create_lab(ctx, chamber_capacity=chamber_capacity)
    return ctx


def setup_rig_with_reservation(
    window_start: str = "2026-08-10T06:00:00Z",
    window_end: str = "2026-08-10T18:00:00Z",
    **kwargs,
) -> dict:
    """A rig holding one reservation over the named window, for the
    hoist-conflict scenarios."""
    ctx = new_project(**kwargs)
    add_zone_a(ctx)
    create_rig(ctx)
    create_reservation(ctx, ctx["zone_ids"][0], window_start, window_end)
    return ctx


def setup_package_with_zone(**kwargs) -> dict:
    """A qualified package with zone A created but nothing released."""
    ctx = setup_qualified_package(**kwargs)
    add_zone_a(ctx)
    return ctx
