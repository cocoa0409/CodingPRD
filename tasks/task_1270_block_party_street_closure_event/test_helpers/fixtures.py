"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch via PRD-declared endpoints (each
test runs against a fresh server). Happy-path steps use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error naming the step.
"""
import math

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    DEFAULT_EVENT_END,
    DEFAULT_EVENT_START,
    SETUP_CLOCK,
)
from .factories import (
    create_contribution_payload,
    create_cost_share_pool_payload,
    create_equipment_stock_payload,
    create_insurance_payload,
    create_organizer_payload,
    create_permit_application_payload,
    create_petition_payload,
    create_post_event_report_payload,
    create_reservation_payload,
    create_signature_payload,
    create_sound_plan_payload,
    create_street_segment_payload,
    create_traffic_control_plan_payload,
    inspect_report_payload,
    petition_verify_payload,
    return_payload,
    review_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_depot_officer_headers, make_organizer_headers

ADMIN = TEST_USERS["city_admin_headers"]
OFFICER = TEST_USERS["permit_officer_headers"]
NEIGHBOR = TEST_USERS["neighbor_headers"]
TRAFFIC = TEST_USERS["traffic_reviewer_headers"]
SAFETY = TEST_USERS["safety_reviewer_headers"]
DEPOT_1 = TEST_USERS["depot_officer_1_headers"]
DEPOT_2 = TEST_USERS["depot_officer_2_headers"]


def _setup_ok(resp, label: str) -> dict:
    data = get_success_data(resp)
    assert isinstance(data, dict), (
        f"Setup failed at {label}: HTTP {resp.status_code} {resp.text}"
    )
    return data


def _setup_ok_list(resp, label: str) -> list:
    data = get_success_data(resp)
    assert isinstance(data, list), (
        f"Setup failed at {label}: HTTP {resp.status_code} {resp.text}"
    )
    return data


# ─── Leaf happy-path helpers ─────────────────────────────

def set_logical_clock(to_iso8601: str = SETUP_CLOCK) -> dict:
    return _setup_ok(api_client.set_current_utc(set_clock_payload(to_iso8601), ADMIN), "set clock")


def create_organizer_record(**overrides) -> dict:
    return _setup_ok(
        api_client.create_organizer(create_organizer_payload(**overrides), TEST_USERS["anonymous_headers"]),
        "create organizer",
    )


def create_segment_record(**overrides) -> dict:
    return _setup_ok(
        api_client.create_street_segment(create_street_segment_payload(**overrides), ADMIN),
        "create street segment",
    )


def create_petition_record(organizer: dict, segment: dict) -> dict:
    return _setup_ok(
        api_client.create_petition(
            create_petition_payload(segment["id"]), make_organizer_headers(organizer["id"])
        ),
        "create petition",
    )


def add_signature_record(petition_id: str, **overrides) -> dict:
    return _setup_ok(
        api_client.add_signature(petition_id, create_signature_payload(**overrides), NEIGHBOR),
        "add signature",
    )


def submit_petition_record(petition_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.submit_petition(petition_id, make_organizer_headers(organizer["id"])),
        "submit petition",
    )


def verify_petition_record(petition_id: str, decision: str = "APPROVE", note=None) -> dict:
    return _setup_ok(
        api_client.verify_petition(petition_id, petition_verify_payload(decision, note), OFFICER),
        "verify petition",
    )


def cure_petition_record(petition_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.cure_petition(petition_id, make_organizer_headers(organizer["id"])),
        "cure petition",
    )


def create_application_record(petition: dict, organizer: dict, **overrides) -> dict:
    return _setup_ok(
        api_client.create_permit_application(
            create_permit_application_payload(petition["id"], **overrides),
            make_organizer_headers(organizer["id"]),
        ),
        "create permit application",
    )


def submit_application_record(application: dict, organizer: dict) -> dict:
    return _setup_ok(
        api_client.submit_permit_application(application["id"], make_organizer_headers(organizer["id"])),
        "submit application",
    )


def patch_application_record(application_id: str, organizer: dict, payload: dict) -> dict:
    return _setup_ok(
        api_client.patch_permit_application(application_id, payload, make_organizer_headers(organizer["id"])),
        "patch application",
    )


def create_tcp_record(application: dict, organizer: dict, **overrides) -> dict:
    return _setup_ok(
        api_client.create_traffic_control_plan(
            application["id"], create_traffic_control_plan_payload(**overrides),
            make_organizer_headers(organizer["id"]),
        ),
        "create traffic control plan",
    )


def submit_tcp_record(plan_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.submit_traffic_control_plan(plan_id, make_organizer_headers(organizer["id"])),
        "submit traffic control plan",
    )


def review_tcp_record(plan_id: str, decision: str = "APPROVE", note=None) -> dict:
    return _setup_ok(
        api_client.review_traffic_control_plan(plan_id, review_payload(decision, note), TRAFFIC),
        "review traffic control plan",
    )


def create_sound_plan_record(application: dict, organizer: dict, **overrides) -> dict:
    return _setup_ok(
        api_client.create_sound_plan(
            application["id"], create_sound_plan_payload(**overrides),
            make_organizer_headers(organizer["id"]),
        ),
        "create sound plan",
    )


def submit_sound_plan_record(plan_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.submit_sound_plan(plan_id, make_organizer_headers(organizer["id"])),
        "submit sound plan",
    )


def review_sound_plan_record(plan_id: str, decision: str = "APPROVE", note=None) -> dict:
    return _setup_ok(
        api_client.review_sound_plan(plan_id, review_payload(decision, note), SAFETY),
        "review sound plan",
    )


def get_application_record(application_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.get_permit_application(application_id, make_organizer_headers(organizer["id"])),
        "get application",
    )


def create_insurance_record(application_id: str, organizer: dict, expected_application_version: int,
                            **overrides) -> dict:
    return _setup_ok(
        api_client.create_insurance_certificate(
            application_id,
            create_insurance_payload(expected_application_version, **overrides),
            make_organizer_headers(organizer["id"]),
        ),
        "create insurance record",
    )


def review_insurance_record(certificate_id: str, decision: str = "APPROVE", note=None) -> dict:
    return _setup_ok(
        api_client.review_insurance_certificate(certificate_id, review_payload(decision, note), SAFETY),
        "review insurance record",
    )


def create_stock_record(**overrides) -> dict:
    return _setup_ok(
        api_client.create_equipment_stock(create_equipment_stock_payload(**overrides), ADMIN),
        "create equipment stock",
    )


def create_reservation_record(application: dict, organizer: dict, equipment_kind: str, units: int) -> dict:
    return _setup_ok(
        api_client.create_equipment_reservation(
            application["id"], create_reservation_payload(equipment_kind, units),
            make_organizer_headers(organizer["id"]),
        ),
        "create equipment reservation",
    )


def create_deposit_record(application: dict, organizer: dict) -> dict:
    return _setup_ok(
        api_client.create_deposit(application["id"], make_organizer_headers(organizer["id"])),
        "create deposit",
    )


def approve_application_record(application_id: str) -> dict:
    return _setup_ok(api_client.approve_permit_application(application_id, OFFICER), "approve application")


def issue_application_record(application_id: str) -> dict:
    return _setup_ok(api_client.issue_permit_application(application_id, OFFICER), "issue application")


def create_pool_record(application: dict, organizer: dict, target_cents: int) -> dict:
    return _setup_ok(
        api_client.create_cost_share_pool(
            application["id"], create_cost_share_pool_payload(target_cents),
            make_organizer_headers(organizer["id"]),
        ),
        "create cost share pool",
    )


def contribute_record(pool_id: str, **overrides) -> dict:
    return _setup_ok(
        api_client.create_contribution(pool_id, create_contribution_payload(**overrides), NEIGHBOR),
        "create contribution",
    )


def dispatch_reservation_record(reservation_id: str, officer_headers=DEPOT_1) -> dict:
    return _setup_ok(
        api_client.dispatch_equipment_reservation(reservation_id, officer_headers),
        "dispatch reservation",
    )


def return_reservation_record(reservation_id: str, returned_units: int, officer_headers=DEPOT_1) -> dict:
    return _setup_ok(
        api_client.return_equipment_reservation(reservation_id, return_payload(returned_units), officer_headers),
        "return reservation",
    )


def pay_reservation_record(reservation_id: str, organizer: dict) -> dict:
    return _setup_ok(
        api_client.pay_equipment_reservation(reservation_id, make_organizer_headers(organizer["id"])),
        "pay reservation",
    )


def verify_return_record(reservation_id: str, officer_headers=DEPOT_2) -> dict:
    return _setup_ok(
        api_client.verify_return_equipment_reservation(reservation_id, officer_headers),
        "verify return",
    )


def create_report_record(application: dict, organizer: dict, **overrides) -> dict:
    return _setup_ok(
        api_client.create_post_event_report(
            application["id"], create_post_event_report_payload(**overrides),
            make_organizer_headers(organizer["id"]),
        ),
        "create post-event report",
    )


def min_barricades_for(segment: dict) -> int:
    """PRD §3.4 segment barricade minimum: ceil(length_m / 12) + 4 when arterial."""
    required = math.ceil(segment["length_m"] / 12)
    if segment.get("intersects_arterial"):
        required += 4
    return required


# ─── Tier 1/2: petition + application progression ────────

def setup_petition(
    *,
    clock: str = SETUP_CLOCK,
    organizer_overrides=None,
    segment_overrides=None,
    signatures=None,
    outcome: str = "verified",
    deficient_note: str = "signature row unreadable",
) -> dict:
    """Organizer + segment + petition walked to `outcome`.

    outcome: "collecting" | "submitted" | "verified" | "deficient".
    Default segment: CITY RESIDENTIAL, 5 households (required_signatures 3).
    Default signatures: three distinct-household rows (meets the default threshold).
    """
    ctx = {}
    set_logical_clock(clock)
    organizer = create_organizer_record(**(organizer_overrides or {}))
    segment = create_segment_record(**(segment_overrides or {}))
    petition = create_petition_record(organizer, segment)
    ctx.update(organizer=organizer, segment=segment, petition=petition)

    if signatures is None:
        signatures = [
            {"household_address": "1 Block St", "signer_name": "Signer One", "signer_email": "sig1@example.com"},
            {"household_address": "2 Block St", "signer_name": "Signer Two", "signer_email": "sig2@example.com"},
            {"household_address": "3 Block St", "signer_name": "Signer Three", "signer_email": "sig3@example.com"},
        ]
    ctx["signatures"] = [add_signature_record(petition["id"], **s) for s in signatures]

    if outcome in ("submitted", "verified", "deficient"):
        ctx["petition"] = submit_petition_record(petition["id"], organizer)
    if outcome == "verified":
        ctx["petition"] = verify_petition_record(petition["id"], "APPROVE")
    elif outcome == "deficient":
        ctx["petition"] = verify_petition_record(petition["id"], "DEFICIENT", note=deficient_note)
    return ctx


def setup_draft_application(*, petition_ctx=None, application_overrides=None, **petition_kwargs) -> dict:
    """Petition ctx (default verified) + one DRAFT application."""
    ctx = petition_ctx or setup_petition(**petition_kwargs)
    application = create_application_record(ctx["petition"], ctx["organizer"], **(application_overrides or {}))
    ctx["application"] = application
    return ctx


def setup_under_review_application(*, petition_ctx=None, application_overrides=None, **petition_kwargs) -> dict:
    """DRAFT application submitted to UNDER_REVIEW (petition VERIFIED by default)."""
    ctx = setup_draft_application(
        petition_ctx=petition_ctx, application_overrides=application_overrides, **petition_kwargs
    )
    ctx["application"] = submit_application_record(ctx["application"], ctx["organizer"])
    return ctx


# ─── Tier 3/5: review lanes through issuance ─────────────

def setup_approvable_application(
    *,
    application_overrides=None,
    tcp_overrides=None,
    tcp_before_submit=False,
    sound_overrides=None,
    insurance_overrides=None,
    stocks=None,
    reservations=None,
    with_deposit=True,
    **petition_kwargs,
) -> dict:
    """UNDER_REVIEW application with every approval gate green (PRD §3.5):
    TCP approved, sound plan approved when amplified, insurance VERIFIED,
    reservations covering the plan counts, deposit HELD.

    tcp_before_submit=True drafts the plan while the application is still DRAFT so
    the provisional fee prices the plan's counts at submit time (PRD §3.3).
    """
    ctx = setup_draft_application(application_overrides=application_overrides, **petition_kwargs)
    organizer = ctx["organizer"]
    app = ctx["application"]

    tcp_fields = dict(tcp_overrides or {})
    tcp_fields.setdefault("barricade_count", min_barricades_for(ctx["segment"]))
    if tcp_before_submit:
        tcp = create_tcp_record(app, organizer, **tcp_fields)
        ctx["tcp"] = tcp
    ctx["application"] = submit_application_record(app, organizer)
    app = ctx["application"]
    if not tcp_before_submit:
        tcp = create_tcp_record(app, organizer, **tcp_fields)
        ctx["tcp"] = tcp
    ctx["tcp"] = submit_tcp_record(ctx["tcp"]["id"], organizer)
    ctx["tcp"] = review_tcp_record(ctx["tcp"]["id"], "APPROVE")

    if app["amplified_sound"]:
        sound = create_sound_plan_record(app, organizer, **(sound_overrides or {}))
        ctx["sound_plan"] = submit_sound_plan_record(sound["id"], organizer)
        ctx["sound_plan"] = review_sound_plan_record(sound["id"], "APPROVE")

    current = get_application_record(app["id"], organizer)
    insurance = create_insurance_record(
        app["id"], organizer, current["version"], **(insurance_overrides or {})
    )
    ctx["insurance"] = review_insurance_record(insurance["id"], "APPROVE")

    ctx["stocks"] = [create_stock_record(**s) for s in (stocks or [])]
    ctx["reservations"] = [
        create_reservation_record(app, organizer, r["equipment_kind"], r["units"])
        for r in (reservations or [])
    ]
    if with_deposit:
        ctx["deposit"] = create_deposit_record(app, organizer)
    ctx["application"] = get_application_record(app["id"], organizer)
    return ctx


def setup_issued_application(**kwargs) -> dict:
    """Full lifecycle through APPROVED -> ISSUED (petition + plans LOCKED,
    reservations CONFIRMED/INVOICED, final fee frozen)."""
    ctx = setup_approvable_application(**kwargs)
    app_id = ctx["application"]["id"]
    ctx["application"] = approve_application_record(app_id)
    ctx["application"] = issue_application_record(app_id)
    # Refresh child views after issuance mutations.
    organizer = ctx["organizer"]
    ctx["petition"] = _setup_ok(
        api_client.get_petition(ctx["petition"]["id"], make_organizer_headers(organizer["id"])),
        "get petition after issue",
    )
    ctx["tcp"] = _setup_ok(
        api_client.get_traffic_control_plan(ctx["tcp"]["id"], make_organizer_headers(organizer["id"])),
        "get tcp after issue",
    )
    ctx["reservations"] = [
        _setup_ok(
            api_client.get_equipment_reservation(r["id"], make_organizer_headers(organizer["id"])),
            "get reservation after issue",
        )
        for r in ctx.get("reservations", [])
    ]
    return ctx


def dispatch_then_return(ctx: dict, *, reservation_index: int = 0, returned_units=None,
                         dispatch_at: str, return_at: str, officer=DEPOT_1) -> dict:
    """Issued ctx -> dispatch inside the window -> return at the given clock."""
    reservation = ctx["reservations"][reservation_index]
    set_logical_clock(dispatch_at)
    ctx["reservations"][reservation_index] = dispatch_reservation_record(reservation["id"], officer)
    set_logical_clock(return_at)
    units = reservation["units"] if returned_units is None else returned_units
    ctx["reservations"][reservation_index] = return_reservation_record(reservation["id"], units, officer)
    return ctx
