"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server whose logical
clock reads 2026-08-01T00:00:00Z and whose database is empty). Setup calls
use get_success_data so failures surface as clear "Setup failed" errors.

The recurring chain in this domain is the booking pipeline:
rate card (PUBLISHED) -> face + permit -> advertiser -> campaign ->
HELD flight -> submit/approve -> confirm (BOOKED) -> artwork DELIVERED
(ART_CLEARED) -> clock to start_date + verified posting (LIVE).
Each tier below terminates one step deeper and returns a bundle dict of every
entity created along the way.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    confirm_flight_payload,
    create_advertiser_payload,
    create_artwork_order_payload,
    create_campaign_payload,
    create_face_payload,
    create_flight_payload,
    create_impression_entry_payload,
    create_permit_payload,
    create_posting_record_payload,
    create_rate_card_payload,
    create_work_order_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_installer_headers,
    make_operations_auditor_headers,
)

PA = TEST_USERS["platform_admin_headers"]
IM = TEST_USERS["inventory_manager_headers"]
SP = TEST_USERS["sales_planner_headers"]
SM = TEST_USERS["sales_manager_headers"]
PC = TEST_USERS["production_coordinator_headers"]
FI = TEST_USERS["field_installer_headers"]
OA = TEST_USERS["operations_auditor_headers"]
CO = TEST_USERS["compliance_officer_headers"]
FA = TEST_USERS["finance_analyst_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 0 — clock and fresh reads
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin-only capability)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), PA)
    return _ok("set_clock", resp)


def face_version(face_id):
    return _ok("get_face", api_client.get_face(face_id, SP))["version"]


def campaign_version(campaign_id):
    return _ok("get_campaign", api_client.get_campaign(campaign_id, SP))["version"]


# ---------------------------------------------------------------------------
# Tier 1 — inventory stand-up
# ---------------------------------------------------------------------------

def create_published_rate_card(**overrides):
    """Create a rate card and drive it DRAFT -> PUBLISHED. Returns the card."""
    card = _ok("create_rate_card",
               api_client.create_rate_card(create_rate_card_payload(**overrides), IM))
    resp = api_client.update_rate_card(
        card["id"],
        {"status": "PUBLISHED", "expected_rate_card_version": card["version"]},
        IM,
    )
    return _ok("publish_rate_card", resp, expected="PUBLISHED")


def create_face_with_permit(face_code="F-NYC-001", display_type="STATIC",
                            illuminated=True, daily_traffic_count=300_000,
                            loop_slots_total=None,
                            width_inches=TEST_DEFAULTS["FACE_WIDTH"],
                            height_inches=TEST_DEFAULTS["FACE_HEIGHT"],
                            permit_expires=TEST_DEFAULTS["PERMIT_EXPIRES"],
                            permit_issued=TEST_DEFAULTS["PERMIT_ISSUED"],
                            permit_number="P-001", file_permit=True):
    """Register a face and (optionally) file its permit. Returns (face, permit)."""
    face_overrides = {
        "face_code": face_code,
        "structure_code": f"ST-{face_code}",
        "display_type": display_type,
        "illuminated": illuminated,
        "daily_traffic_count": daily_traffic_count,
        "width_inches": width_inches,
        "height_inches": height_inches,
    }
    if loop_slots_total is not None:
        face_overrides["loop_slots_total"] = loop_slots_total
    face = _ok("create_face",
               api_client.create_face(create_face_payload(**face_overrides), IM))
    permit = None
    if file_permit:
        permit = _ok(
            "create_permit",
            api_client.create_permit(
                create_permit_payload(
                    face["id"], permit_number=permit_number,
                    issued_on=permit_issued, expires_on=permit_expires,
                ),
                CO,
            ),
            expected="ACTIVE",
        )
    return face, permit


def create_advertiser(credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
                      name=TEST_DEFAULTS["ADVERTISER_NAME"]):
    resp = api_client.create_advertiser(
        create_advertiser_payload(name=name, credit_limit_cents=credit_limit_cents),
        SP,
    )
    return _ok("create_advertiser", resp, expected="ACTIVE")


def create_campaign(advertiser_id, start_date=TEST_DEFAULTS["CAMPAIGN_START"],
                    end_date=TEST_DEFAULTS["CAMPAIGN_END"], name="C1"):
    resp = api_client.create_campaign(
        create_campaign_payload(advertiser_id, name=name,
                                start_date=start_date, end_date=end_date),
        SP,
    )
    return _ok("create_campaign", resp, expected="DRAFT")


# ---------------------------------------------------------------------------
# Tier 2 — flight holds and the approval chain
# ---------------------------------------------------------------------------

def hold_flight(campaign_id, face_id, rate_card_id,
                start_date=TEST_DEFAULTS["FLIGHT_START"],
                end_date=TEST_DEFAULTS["FLIGHT_END"], loop_slots=None,
                predecessor_flight_id=None):
    """Create a HELD flight, reading the face fresh for the OCC guard."""
    overrides = {}
    if loop_slots is not None:
        overrides["loop_slots"] = loop_slots
    if predecessor_flight_id is not None:
        overrides["predecessor_flight_id"] = predecessor_flight_id
    resp = api_client.create_flight(
        create_flight_payload(
            campaign_id, face_id, rate_card_id,
            expected_face_version=face_version(face_id),
            start_date=start_date, end_date=end_date, **overrides,
        ),
        SP,
    )
    return _ok("create_flight", resp, expected="HELD")


def submit_campaign(campaign_id):
    resp = api_client.update_campaign(campaign_id, {"status": "SUBMITTED"}, SP)
    return _ok("submit_campaign", resp, expected="SUBMITTED")


def approve_campaign(campaign_id):
    resp = api_client.update_campaign(campaign_id, {"status": "APPROVED"}, SM)
    return _ok("approve_campaign", resp, expected="APPROVED")


def submit_and_approve_campaign(campaign_id):
    submit_campaign(campaign_id)
    return approve_campaign(campaign_id)


def confirm_flight(flight_id, campaign_id):
    """Confirm a HELD flight, reading the campaign fresh for the OCC guard."""
    resp = api_client.confirm_flight(
        flight_id,
        confirm_flight_payload(expected_campaign_version=campaign_version(campaign_id)),
        SP,
    )
    return _ok("confirm_flight", resp, expected="BOOKED")


# ---------------------------------------------------------------------------
# Tier 3 — artwork pipeline and posting verification
# ---------------------------------------------------------------------------

def deliver_artwork(flight_id, creative_code="CR-1", material="VINYL",
                    width_inches=TEST_DEFAULTS["FACE_WIDTH"],
                    height_inches=TEST_DEFAULTS["FACE_HEIGHT"]):
    """Submit an artwork order and drive it to DELIVERED. Returns the order."""
    order = _ok(
        "create_artwork_order",
        api_client.create_artwork_order(
            create_artwork_order_payload(
                flight_id, creative_code=creative_code, material=material,
                width_inches=width_inches, height_inches=height_inches,
            ),
            PC,
        ),
        expected="SUBMITTED",
    )
    for status in ("IN_PRODUCTION", "PRINTED", "SHIPPED", "DELIVERED"):
        order = _ok(f"artwork_{status}",
                    api_client.update_artwork_order(order["id"], {"status": status}, PC),
                    expected=status)
    return order


def report_posting(flight_id, posted_on=TEST_DEFAULTS["FLIGHT_START"],
                   installer_id="installer-1",
                   photo_proof_url="https://proof.example/1.jpg"):
    """FieldInstaller reports a posting. Returns the REPORTED record."""
    resp = api_client.create_posting_record(
        create_posting_record_payload(flight_id, posted_on=posted_on,
                                      photo_proof_url=photo_proof_url),
        make_field_installer_headers(installer_id),
    )
    return _ok("create_posting_record", resp, expected="REPORTED")


def verify_posting(posting_record_id, auditor_id="auditor-1"):
    """OperationsAuditor verifies a posting. Returns the VERIFIED record."""
    resp = api_client.update_posting_record(
        posting_record_id, {"status": "VERIFIED"},
        make_operations_auditor_headers(auditor_id),
    )
    return _ok("verify_posting", resp, expected="VERIFIED")


# ---------------------------------------------------------------------------
# Tier 4 — composite booking-chain bundles
# ---------------------------------------------------------------------------

def setup_held_flight(rate_card_overrides=None, face_kwargs=None,
                      advertiser_limit=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
                      campaign_start=TEST_DEFAULTS["CAMPAIGN_START"],
                      campaign_end=TEST_DEFAULTS["CAMPAIGN_END"],
                      flight_start=TEST_DEFAULTS["FLIGHT_START"],
                      flight_end=TEST_DEFAULTS["FLIGHT_END"],
                      loop_slots=None):
    """Card PUBLISHED + face with permit + advertiser + DRAFT campaign + HELD flight."""
    rate_card = create_published_rate_card(**(rate_card_overrides or {}))
    face, permit = create_face_with_permit(**(face_kwargs or {}))
    advertiser = create_advertiser(credit_limit_cents=advertiser_limit)
    campaign = create_campaign(advertiser["id"], start_date=campaign_start,
                               end_date=campaign_end)
    flight = hold_flight(campaign["id"], face["id"], rate_card["id"],
                         start_date=flight_start, end_date=flight_end,
                         loop_slots=loop_slots)
    return {
        "rate_card": rate_card, "face": face, "permit": permit,
        "advertiser": advertiser, "campaign": campaign, "flight": flight,
    }


def setup_booked_flight(**kwargs):
    """setup_held_flight + campaign SUBMITTED/APPROVED + flight confirmed BOOKED."""
    bundle = setup_held_flight(**kwargs)
    submit_and_approve_campaign(bundle["campaign"]["id"])
    bundle["campaign"] = _ok(
        "get_campaign", api_client.get_campaign(bundle["campaign"]["id"], SP))
    bundle["flight"] = confirm_flight(bundle["flight"]["id"], bundle["campaign"]["id"])
    return bundle


def setup_art_cleared_flight(**kwargs):
    """setup_booked_flight + artwork DELIVERED (flight ART_CLEARED)."""
    bundle = setup_booked_flight(**kwargs)
    face = bundle["face"]
    material = "DIGITAL_FILE" if face["display_type"] == "DIGITAL" else "VINYL"
    bundle["artwork"] = deliver_artwork(
        bundle["flight"]["id"], material=material,
        width_inches=face["width_inches"], height_inches=face["height_inches"],
    )
    bundle["flight"] = _ok(
        "get_flight", api_client.get_flight(bundle["flight"]["id"], SP))
    assert bundle["flight"]["status"] == "ART_CLEARED", (
        f"Setup failed: expected ART_CLEARED after artwork delivery, "
        f"got {bundle['flight']['status']}"
    )
    return bundle


def setup_live_flight(posted_on=None, clock_to_start=True, **kwargs):
    """setup_art_cleared_flight + clock to start_date + verified posting (LIVE)."""
    bundle = setup_art_cleared_flight(**kwargs)
    if clock_to_start:
        set_clock(f"{bundle['flight']['start_date']}T00:00:00Z")
    posting = report_posting(
        bundle["flight"]["id"],
        posted_on=posted_on or bundle["flight"]["start_date"],
    )
    bundle["posting"] = verify_posting(posting["id"])
    bundle["flight"] = _ok(
        "get_flight", api_client.get_flight(bundle["flight"]["id"], SP))
    assert bundle["flight"]["status"] == "LIVE", (
        f"Setup failed: expected LIVE after verified posting, "
        f"got {bundle['flight']['status']}"
    )
    return bundle


# ---------------------------------------------------------------------------
# Tier 5 — maintenance and permit helpers
# ---------------------------------------------------------------------------

def create_work_order(face_id, order_type="STRUCTURAL_REPAIR",
                      description="panel refit"):
    resp = api_client.create_work_order(
        create_work_order_payload(face_id, order_type=order_type,
                                  description=description),
        CO,
    )
    return _ok("create_work_order", resp, expected="OPEN")


def transition_work_order(work_order_id, status, expected=None, **fields):
    payload = {"status": status}
    payload.update(fields)
    resp = api_client.update_work_order(work_order_id, payload, CO)
    return _ok(f"work_order_{status}", resp, expected=expected or status)


def append_impression_entry(flight_id, period_start, period_end, source,
                            impressions, auditor_id="auditor-1"):
    resp = api_client.append_impression_entry(
        flight_id,
        create_impression_entry_payload(
            period_start=period_start, period_end=period_end,
            source=source, impressions=impressions,
        ),
        make_operations_auditor_headers(auditor_id),
    )
    return _ok("append_impression_entry", resp)
