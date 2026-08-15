"""Composite setup helpers: multi-step workflows built from PRD endpoints.

Every helper builds its preconditions from scratch (each test runs against a
fresh server/database) using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Bundle convention: composite helpers return a dict whose keys name the
created entities, e.g. {"convention": ..., "spaces": {"A-101": ...},
"exhibitor": ..., "application": ..., "placements": [...], "placement": ...}.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_JURY_REVIEW,
    CLOCK_LIVE_START,
    CLOCK_OPEN_SUBMIT,
)
from .factories import (
    create_application_payload,
    create_convention_payload,
    create_exhibitor_payload,
    create_freight_booking_payload,
    create_issue_ticket_payload,
    create_jury_score_payload,
    create_load_slot_payload,
    create_neighbor_request_payload,
    create_placement_payload,
    create_sales_report_payload,
    create_space_unit_payload,
    create_staff_member_payload,
    submit_permit_payload,
)
from .test_users import (
    TEST_USERS,
    make_anonymous_headers,
    make_director_headers,
    make_exhibitor_headers,
    make_juror_headers,
    make_ops_headers,
)

# ---------------------------------------------------------------------------
# Standard jury score sets (PRD Section 3.4 weights 0.35/0.25/0.25/0.15)
# ---------------------------------------------------------------------------
# Composite 77.67: per-juror weighted totals 77.00, 83.50, 72.50.
STANDARD_SCORES = [
    ("juror-1", 80, 90, 70, 60),
    ("juror-2", 90, 80, 80, 80),
    ("juror-3", 70, 70, 80, 70),
]
# Composite 60.00: qualifies for WAITLISTED only.
SCORES_60 = [
    ("juror-1", 60, 60, 60, 60),
    ("juror-2", 60, 60, 60, 60),
    ("juror-3", 60, 60, 60, 60),
]
# Composite 40.00: rejection only.
SCORES_40 = [
    ("juror-1", 40, 40, 40, 40),
    ("juror-2", 40, 40, 40, 40),
    ("juror-3", 40, 40, 40, 40),
]

DEFAULT_SPACE_SPEC = {
    "space_code": "A-101",
    "block": "A",
    "unit_number": 101,
    "hall": "MAIN",
    "kind": "BOOTH_10X10",
    "base_price_cents": 100000,
}


# ---------------------------------------------------------------------------
# Primitive step helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["director_headers"])
    )


def create_convention(category_quotas=None, dock_doors=None, **overrides) -> dict:
    payload = create_convention_payload(
        category_quotas=category_quotas, dock_doors=dock_doors, **overrides
    )
    return get_success_data(
        api_client.create_convention(payload, TEST_USERS["director_headers"]), 201
    )


def get_convention(convention_id) -> dict:
    return get_success_data(
        api_client.get_convention(convention_id, TEST_USERS["director_headers"])
    )


def advance_phase(convention_id) -> dict:
    return get_success_data(
        api_client.advance_phase(convention_id, TEST_USERS["director_headers"])
    )


def run_ops(convention_id) -> dict:
    return get_success_data(
        api_client.run_ops(convention_id, TEST_USERS["director_headers"])
    )


def create_space_unit(convention_id, **overrides) -> dict:
    payload = create_space_unit_payload(convention_id, **overrides)
    return get_success_data(
        api_client.create_space_unit(payload, TEST_USERS["director_headers"]), 201
    )


def get_space_unit(space_unit_id) -> dict:
    return get_success_data(
        api_client.get_space_unit(space_unit_id, TEST_USERS["director_headers"])
    )


def list_space_units(params=None) -> list:
    return get_success_data(
        api_client.list_space_units(TEST_USERS["director_headers"], params=params)
    )


def find_dock_door(convention_id, door_code) -> dict:
    doors = get_success_data(
        api_client.list_dock_doors(
            TEST_USERS["director_headers"],
            params={"convention_id": convention_id, "door_code": door_code},
        )
    )
    assert len(doors) == 1, f"expected exactly one dock door {door_code}"
    return doors[0]


def get_quota(convention_id, category) -> dict:
    quotas = get_success_data(
        api_client.list_category_quotas(
            TEST_USERS["director_headers"],
            params={"convention_id": convention_id, "category": category},
        )
    )
    assert len(quotas) == 1, f"expected exactly one {category} quota"
    return quotas[0]


def register_exhibitor(**overrides) -> dict:
    payload = create_exhibitor_payload(**overrides)
    return get_success_data(
        api_client.create_exhibitor(payload, make_anonymous_headers()), 201
    )


def get_exhibitor(exhibitor_id) -> dict:
    return get_success_data(
        api_client.get_exhibitor(exhibitor_id, TEST_USERS["director_headers"])
    )


def create_application(convention_id, exhibitor_id, **overrides) -> dict:
    payload = create_application_payload(convention_id, **overrides)
    return get_success_data(
        api_client.create_application(payload, make_exhibitor_headers(exhibitor_id)),
        201,
    )


def get_application(application_id) -> dict:
    return get_success_data(
        api_client.get_application(application_id, TEST_USERS["director_headers"])
    )


def submit_application(application_id, exhibitor_id) -> dict:
    return get_success_data(
        api_client.submit_application(
            application_id, make_exhibitor_headers(exhibitor_id)
        )
    )


def withdraw_application(application_id, exhibitor_id) -> dict:
    return get_success_data(
        api_client.withdraw_application(
            application_id, make_exhibitor_headers(exhibitor_id)
        )
    )


def post_jury_score(
    application_id, juror_user_id, originality, craft, category_fit, professionalism
) -> dict:
    payload = create_jury_score_payload(
        application_id,
        originality=originality,
        craft=craft,
        category_fit=category_fit,
        professionalism=professionalism,
    )
    return get_success_data(
        api_client.create_jury_score(payload, make_juror_headers(juror_user_id)), 201
    )


def post_scores(application_id, scores=STANDARD_SCORES) -> list:
    return [
        post_jury_score(application_id, juror, o, c, f, p)
        for (juror, o, c, f, p) in scores
    ]


def decide(application_id, decision) -> dict:
    return get_success_data(
        api_client.decide_application(
            application_id, {"decision": decision}, TEST_USERS["director_headers"]
        )
    )


def request_revision(application_id) -> dict:
    return get_success_data(
        api_client.request_revision(application_id, TEST_USERS["director_headers"])
    )


def create_placement(application_id, space_unit_id) -> dict:
    payload = create_placement_payload(application_id, space_unit_id)
    return get_success_data(
        api_client.create_placement(payload, TEST_USERS["director_headers"]), 201
    )


def confirm_placement(placement_id) -> dict:
    return get_success_data(
        api_client.confirm_placement(placement_id, TEST_USERS["director_headers"])
    )


def release_placement(placement_id) -> dict:
    return get_success_data(
        api_client.release_placement(placement_id, TEST_USERS["director_headers"])
    )


def submit_and_verify_permit(application_id, exhibitor_id, **permit_overrides) -> dict:
    get_success_data(
        api_client.submit_permit(
            application_id,
            submit_permit_payload(**permit_overrides),
            make_exhibitor_headers(exhibitor_id),
        )
    )
    return get_success_data(
        api_client.verify_permit(application_id, TEST_USERS["director_headers"])
    )


def accept_offer(application_id, exhibitor_id, deposit_cents) -> dict:
    return get_success_data(
        api_client.accept_offer(
            application_id,
            {"deposit_cents": deposit_cents},
            make_exhibitor_headers(exhibitor_id),
        )
    )


def create_neighbor_request(convention_id, requester_id, target_id, kind) -> dict:
    payload = create_neighbor_request_payload(
        convention_id, target_id, kind=kind
    )
    return get_success_data(
        api_client.create_neighbor_request(
            payload, make_exhibitor_headers(requester_id)
        ),
        201,
    )


def create_staff_member(convention_id, exhibitor_id, full_name, **overrides) -> dict:
    payload = create_staff_member_payload(
        convention_id, full_name=full_name, **overrides
    )
    return get_success_data(
        api_client.create_staff_member(
            payload, make_exhibitor_headers(exhibitor_id)
        ),
        201,
    )


def issue_badge(staff_member_id, exhibitor_id) -> dict:
    return get_success_data(
        api_client.issue_badge(
            staff_member_id, make_exhibitor_headers(exhibitor_id)
        )
    )


def create_load_slot(convention_id, **overrides) -> dict:
    payload = create_load_slot_payload(convention_id, **overrides)
    return get_success_data(
        api_client.create_load_slot(payload, TEST_USERS["director_headers"]), 201
    )


def get_load_slot(load_slot_id) -> dict:
    return get_success_data(
        api_client.get_load_slot(load_slot_id, TEST_USERS["director_headers"])
    )


def create_freight_booking(
    application_id, exhibitor_id, load_slot_id, dock_door_id, **overrides
) -> dict:
    payload = create_freight_booking_payload(
        application_id, load_slot_id, dock_door_id, **overrides
    )
    return get_success_data(
        api_client.create_freight_booking(
            payload, make_exhibitor_headers(exhibitor_id)
        ),
        201,
    )


def confirm_freight_booking(freight_booking_id) -> dict:
    return get_success_data(
        api_client.confirm_freight_booking(
            freight_booking_id, TEST_USERS["ops_headers"]
        )
    )


def report_issue(convention_id, exhibitor_id, reporter="ops", **overrides) -> dict:
    """Report an issue ticket; reporter is OperationsStaff ops-1 by default."""
    headers = make_ops_headers("ops-1") if reporter == "ops" else make_director_headers(reporter)
    payload = create_issue_ticket_payload(convention_id, exhibitor_id, **overrides)
    return get_success_data(api_client.create_issue_ticket(payload, headers), 201)


def resolve_issue(issue_ticket_id, outcome, resolver="dir-1") -> dict:
    return get_success_data(
        api_client.resolve_issue(
            issue_ticket_id, {"outcome": outcome}, make_director_headers(resolver)
        )
    )


def record_guilty_issue(convention_id, exhibitor_id, severity, description) -> dict:
    """Report + resolve GUILTY in one step (reporter ops-1, resolver dir-1)."""
    issue = report_issue(
        convention_id, exhibitor_id, severity=severity, description=description
    )
    return resolve_issue(issue["id"], "GUILTY")


def create_sales_report(application_id, exhibitor_id, **overrides) -> dict:
    payload = create_sales_report_payload(application_id, **overrides)
    return get_success_data(
        api_client.create_sales_report(
            payload, make_exhibitor_headers(exhibitor_id)
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Composite fixtures (Tier 1-5)
# ---------------------------------------------------------------------------

def setup_open_convention(
    space_specs=None,
    clock=CLOCK_OPEN_SUBMIT,
    category_quotas=None,
    dock_doors=None,
    advance=True,
    **convention_overrides,
) -> dict:
    """Tier 2: convention with space inventory, clock set, advanced
    SETUP -> APPLICATIONS_OPEN. Returns {"convention", "spaces"}."""
    conv = create_convention(
        category_quotas=category_quotas, dock_doors=dock_doors, **convention_overrides
    )
    spaces = {}
    for spec in (space_specs if space_specs is not None else [DEFAULT_SPACE_SPEC]):
        unit = create_space_unit(conv["id"], **spec)
        spaces[unit["space_code"]] = unit
    if clock is not None:
        set_clock(clock)
    if advance:
        conv = advance_phase(conv["id"])
    return {"convention": conv, "spaces": spaces}


def setup_submitted_application(
    category="DEALER",
    kinds=("BOOTH_10X10",),
    space_count=1,
    estimated_daily_sales_cents=33333,
    channel="OPEN",
    exhibitor_overrides=None,
    conflicted_juror_user_ids=None,
    submit=True,
    **convention_kwargs,
) -> dict:
    """Tier 1+2: open convention + registered exhibitor + application,
    submitted by default. Bundle keys: convention, spaces, exhibitor,
    application."""
    bundle = setup_open_convention(**convention_kwargs)
    conv = bundle["convention"]
    exhibitor = register_exhibitor(category=category, **(exhibitor_overrides or {}))
    app_overrides = {
        "category": category,
        "channel": channel,
        "requested_space_kinds": list(kinds),
        "requested_space_count": space_count,
        "estimated_daily_sales_cents": estimated_daily_sales_cents,
    }
    if conflicted_juror_user_ids is not None:
        app_overrides["conflicted_juror_user_ids"] = conflicted_juror_user_ids
    application = create_application(conv["id"], exhibitor["id"], **app_overrides)
    if submit:
        application = submit_application(application["id"], exhibitor["id"])
    bundle.update({"exhibitor": exhibitor, "application": application})
    return bundle


def setup_jury_review_application(scores=None, **kwargs) -> dict:
    """Tier 1: submitted application, convention advanced to JURY_REVIEW;
    optionally posts jury scores (first score moves the application to
    UNDER_REVIEW automatically)."""
    bundle = setup_submitted_application(**kwargs)
    conv = bundle["convention"]
    set_clock(CLOCK_JURY_REVIEW)
    bundle["convention"] = advance_phase(conv["id"])
    if scores:
        bundle["jury_scores"] = post_scores(bundle["application"]["id"], scores)
        bundle["application"] = get_application(bundle["application"]["id"])
    return bundle


def setup_decided_application(decision="ACCEPTED", scores=STANDARD_SCORES, **kwargs) -> dict:
    """Tier 3: application scored by three jurors and decided from UNDER_REVIEW."""
    bundle = setup_jury_review_application(scores=scores, **kwargs)
    bundle["application"] = decide(bundle["application"]["id"], decision)
    return bundle


def setup_accepted_with_placements(
    placement_space_codes=None,
    scores=STANDARD_SCORES,
    **kwargs,
) -> dict:
    """Tier 3: JURIED_ACCEPTED application, convention in PLACEMENT, with one
    TENTATIVE placement per listed space code (default: the first space)."""
    bundle = setup_decided_application(decision="ACCEPTED", scores=scores, **kwargs)
    conv = bundle["convention"]
    bundle["convention"] = advance_phase(conv["id"])
    spaces = bundle["spaces"]
    codes = placement_space_codes or [next(iter(spaces))]
    placements = [
        create_placement(bundle["application"]["id"], spaces[code]["id"])
        for code in codes
    ]
    bundle["placements"] = placements
    bundle["placement"] = placements[0]
    bundle["application"] = get_application(bundle["application"]["id"])
    return bundle


def setup_contracted_application(
    deposit_cents=22500,
    verify_permit=True,
    scores=STANDARD_SCORES,
    **kwargs,
) -> dict:
    """Tier 3: accepted application with TENTATIVE placement(s), permit
    VERIFIED, offer accepted (exact deposit) -> CONTRACTED."""
    bundle = setup_accepted_with_placements(scores=scores, **kwargs)
    app_id = bundle["application"]["id"]
    ex_id = bundle["exhibitor"]["id"]
    if verify_permit:
        submit_and_verify_permit(app_id, ex_id)
    bundle["application"] = accept_offer(app_id, ex_id, deposit_cents)
    return bundle


def setup_placed_application(scores=STANDARD_SCORES, **kwargs) -> dict:
    """Tier 3: CONTRACTED application with every TENTATIVE placement confirmed
    -> PLACED (convention still in PLACEMENT phase)."""
    bundle = setup_contracted_application(scores=scores, **kwargs)
    for placement in bundle["placements"]:
        confirm_placement(placement["id"])
    bundle["application"] = get_application(bundle["application"]["id"])
    return bundle


def setup_placed_in_logistics(**kwargs) -> dict:
    """Tier 3: PLACED application; convention advanced PLACEMENT -> LOGISTICS."""
    bundle = setup_placed_application(**kwargs)
    bundle["convention"] = advance_phase(bundle["convention"]["id"])
    return bundle


def setup_placed_in_live(**kwargs) -> dict:
    """Tier 3: PLACED application; convention advanced to LIVE (clock at
    starts_at)."""
    bundle = setup_placed_in_logistics(**kwargs)
    set_clock(CLOCK_LIVE_START)
    bundle["convention"] = advance_phase(bundle["convention"]["id"])
    return bundle


def setup_freight_ready(slot_overrides=None, **kwargs) -> dict:
    """Tier 2 extension: PLACED application in LOGISTICS plus an INBOUND load
    slot and the convention's dock doors. Adds keys: load_slot, doors."""
    bundle = setup_placed_in_logistics(**kwargs)
    conv_id = bundle["convention"]["id"]
    slot = create_load_slot(conv_id, **(slot_overrides or {}))
    doors = {
        door["door_code"]: door
        for door in get_success_data(
            api_client.list_dock_doors(
                TEST_USERS["director_headers"], params={"convention_id": conv_id}
            )
        )
    }
    bundle.update({"load_slot": slot, "doors": doors})
    return bundle


def setup_two_applications_decided(
    decision_a="ACCEPTED",
    decision_b="WAITLISTED",
    scores_a=STANDARD_SCORES,
    scores_b=SCORES_60,
    category="DEALER",
    kinds=("BOOTH_10X10",),
    exhibitor_b_overrides=None,
    estimated_b=20000,
    **convention_kwargs,
) -> dict:
    """Tier 2: one convention; exhibitors A and B each submit an application of
    the same category; convention moved to JURY_REVIEW; both fully scored and
    decided. Pass decision_a=None / decision_b=None to leave that application
    UNDER_REVIEW. Bundle keys: convention, spaces, exhibitor_a, application_a,
    exhibitor_b, application_b."""
    bundle = setup_open_convention(**convention_kwargs)
    conv = bundle["convention"]
    ex_a = register_exhibitor(legal_name="Dealer One LLC", category=category)
    ex_b = register_exhibitor(
        legal_name="Dealer Two LLC",
        category=category,
        **(exhibitor_b_overrides or {}),
    )
    app_a = create_application(
        conv["id"], ex_a["id"], category=category, requested_space_kinds=list(kinds)
    )
    app_b = create_application(
        conv["id"],
        ex_b["id"],
        category=category,
        requested_space_kinds=list(kinds),
        estimated_daily_sales_cents=estimated_b,
    )
    app_a = submit_application(app_a["id"], ex_a["id"])
    app_b = submit_application(app_b["id"], ex_b["id"])
    set_clock(CLOCK_JURY_REVIEW)
    bundle["convention"] = advance_phase(conv["id"])
    post_scores(app_a["id"], scores_a)
    post_scores(app_b["id"], scores_b)
    bundle["application_a"] = (
        decide(app_a["id"], decision_a) if decision_a else get_application(app_a["id"])
    )
    bundle["application_b"] = (
        decide(app_b["id"], decision_b) if decision_b else get_application(app_b["id"])
    )
    bundle.update({"exhibitor_a": ex_a, "exhibitor_b": ex_b})
    return bundle


def setup_accepted_with_placement_for_a(two_app_bundle) -> dict:
    """Extend a two-application bundle: advance to PLACEMENT and offer the
    first space to application A (TENTATIVE)."""
    bundle = two_app_bundle
    conv = bundle["convention"]
    bundle["convention"] = advance_phase(conv["id"])
    space = next(iter(bundle["spaces"].values()))
    bundle["placement"] = create_placement(
        bundle["application_a"]["id"], space["id"]
    )
    bundle["application_a"] = get_application(bundle["application_a"]["id"])
    return bundle


def setup_contracted_for_a(two_app_bundle, deposit_cents=22500) -> dict:
    """Extend further: permit VERIFIED + offer accepted for application A."""
    bundle = setup_accepted_with_placement_for_a(two_app_bundle)
    app_id = bundle["application_a"]["id"]
    ex_id = bundle["exhibitor_a"]["id"]
    submit_and_verify_permit(app_id, ex_id)
    bundle["application_a"] = accept_offer(app_id, ex_id, deposit_cents)
    return bundle


def setup_placed_for_a(two_app_bundle, deposit_cents=22500) -> dict:
    """Extend further: confirm application A's placement -> A is PLACED."""
    bundle = setup_contracted_for_a(two_app_bundle, deposit_cents=deposit_cents)
    confirm_placement(bundle["placement"]["id"])
    bundle["application_a"] = get_application(bundle["application_a"]["id"])
    return bundle
