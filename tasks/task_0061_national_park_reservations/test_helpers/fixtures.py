"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the server is restarted (empty DB) before every test. They mirror the
setup_api_calls chains shared across the design instances:

  - a park, a park_admin scoped to it, and one or more visitors
  - the simulation clock set to a known instant
  - timed-entry slots / lottery draws / campsites / trailheads / zones
  - reservations / permits driven to a target lifecycle state

Helpers assert their setup calls succeed (2xx) so a setup failure surfaces
clearly rather than as a confusing downstream assertion.
"""
import itertools

from .api_client import ApiClient
from .assertions import data_of

_email_counter = itertools.count(1)


def _email(prefix="u"):
    return f"{prefix}{next(_email_counter)}@x.com"


def _ok(resp):
    assert resp.status_code in (200, 201), (
        f"setup call failed {resp.status_code}: {resp.text}"
    )
    return data_of(resp)


# --- clock ----------------------------------------------------------------
def set_clock(client: ApiClient, now_utc):
    return _ok(client.post("/v1/_clock/set_current_utc",
                           role="system", user_id="seed", json={"now_utc": now_utc}))


def run_ops(client: ApiClient):
    return _ok(client.post("/v1/_ops/run", role="park_admin",
                           user_id="ops-operator"))


# --- principals -----------------------------------------------------------
def create_park(client: ApiClient, code, **overrides):
    payload = {"code": code, "name": f"{code} Park", "utc_offset_minutes": 0}
    payload.update(overrides)
    return _ok(client.post("/v1/parks", role="system", user_id="seed", json=payload))


def create_park_admin(client: ApiClient, park_id, **overrides):
    payload = {"email": _email("pa"), "full_name": "PA",
               "birth_date": "1980-01-01", "role": "park_admin",
               "home_park_id": park_id}
    payload.update(overrides)
    return _ok(client.post("/v1/accounts", role="system", user_id="seed", json=payload))


def create_ranger(client: ApiClient, park_id, **overrides):
    payload = {"email": _email("rg"), "full_name": "RG",
               "birth_date": "1980-01-01", "role": "ranger",
               "home_park_id": park_id}
    payload.update(overrides)
    return _ok(client.post("/v1/accounts", role="system", user_id="seed", json=payload))


def create_finance(client: ApiClient, **overrides):
    payload = {"email": _email("fin"), "full_name": "FIN",
               "birth_date": "1980-01-01", "role": "finance"}
    payload.update(overrides)
    return _ok(client.post("/v1/accounts", role="system", user_id="seed", json=payload))


def create_visitor(client: ApiClient, **overrides):
    payload = {"email": _email("v"), "full_name": "V", "birth_date": "1990-01-01"}
    payload.update(overrides)
    return _ok(client.post("/v1/accounts", role="system", user_id="seed", json=payload))


def base_world(client: ApiClient, code, now_utc="2026-06-01T00:00:00Z",
               park_overrides=None):
    """Park + park_admin + clock set. Returns (park, park_admin)."""
    park = create_park(client, code, **(park_overrides or {}))
    set_clock(client, now_utc)
    pa = create_park_admin(client, park["id"])
    return park, pa


# --- inventory ------------------------------------------------------------
def create_campsite(client: ApiClient, park_id, pa_id, site_number="T1",
                    site_type="tent", **overrides):
    payload = {"park_id": park_id, "site_number": site_number,
               "site_type": site_type, "max_occupancy": 6,
               "base_nightly_cents": 4000}
    payload.update(overrides)
    return _ok(client.post("/v1/campsites", role="park_admin",
                           user_id=pa_id, json=payload))


def create_slot(client: ApiClient, park_id, pa_id, **overrides):
    payload = {"park_id": park_id, "entry_date": "2026-06-08",
               "window_start_local": "07:00", "window_end_local": "09:00",
               "capacity": 5, "release_at": "2026-06-05T07:00:00Z",
               "entry_fee_cents": 200}
    payload.update(overrides)
    return _ok(client.post("/v1/timed-entry-slots", role="park_admin",
                           user_id=pa_id, json=payload))


def create_trailhead(client: ApiClient, park_id, pa_id, **overrides):
    payload = {"park_id": park_id, "name": "TH", "daily_exit_quota": 10,
               "reservation_fee_cents": 500, "per_person_per_night_cents": 800}
    payload.update(overrides)
    return _ok(client.post("/v1/trailheads", role="park_admin",
                           user_id=pa_id, json=payload))


def create_zone(client: ApiClient, park_id, pa_id, **overrides):
    payload = {"park_id": park_id, "name": "Z", "nightly_party_quota": 5}
    payload.update(overrides)
    return _ok(client.post("/v1/wilderness-zones", role="park_admin",
                           user_id=pa_id, json=payload))


def create_draw(client: ApiClient, park_id, pa_id, **overrides):
    payload = {"park_id": park_id, "objective": "the_wave",
               "use_date": "2026-09-01", "daily_quota": 10,
               "application_open_at": "2026-05-01T00:00:00Z",
               "application_close_at": "2026-06-01T00:00:00Z",
               "draw_at": "2026-06-02T00:00:00Z",
               "permit_fee_per_person_cents": 1500}
    payload.update(overrides)
    return _ok(client.post("/v1/lottery-draws", role="park_admin",
                           user_id=pa_id, json=payload))


# --- bookings -------------------------------------------------------------
def create_camp_reservation(client: ApiClient, campsite_id, visitor_id,
                            check_in, check_out, party_size=2,
                            idempotency_key=None):
    payload = {"campsite_id": campsite_id, "account_id": visitor_id,
               "check_in": check_in, "check_out": check_out,
               "party_size": party_size}
    return _ok(client.post("/v1/camp-reservations", role="visitor",
                           user_id=visitor_id, json=payload,
                           idempotency_key=idempotency_key))


def confirm_camp_reservation(client: ApiClient, resv_id, visitor_id):
    return _ok(client.post(f"/v1/camp-reservations/{resv_id}/confirm",
                           role="visitor", user_id=visitor_id))


def create_slot_hold(client: ApiClient, slot_id, visitor_id, slot_version,
                     plate="PLT1"):
    payload = {"slot_id": slot_id, "account_id": visitor_id,
               "vehicle_plate": plate, "expected_slot_version": slot_version}
    return _ok(client.post("/v1/timed-entry-reservations", role="visitor",
                           user_id=visitor_id, json=payload))


def create_backcountry_permit(client: ApiClient, park_id, visitor_id,
                              trailhead_id, entry_date, nights, party_size,
                              zone_nights):
    payload = {"park_id": park_id, "account_id": visitor_id,
               "trailhead_id": trailhead_id, "entry_date": entry_date,
               "nights": nights, "party_size": party_size,
               "zone_nights": zone_nights}
    return _ok(client.post("/v1/backcountry-permits", role="visitor",
                           user_id=visitor_id, json=payload))


def confirm_backcountry_permit(client: ApiClient, permit_id, visitor_id):
    return _ok(client.post(f"/v1/backcountry-permits/{permit_id}/confirm",
                           role="visitor", user_id=visitor_id))


def buy_pass(client: ApiClient, visitor_id, pass_type, valid_from):
    payload = {"account_id": visitor_id, "pass_type": pass_type,
               "valid_from": valid_from}
    return _ok(client.post("/v1/atb-passes", role="visitor",
                           user_id=visitor_id, json=payload))


def submit_application(client: ApiClient, draw_id, visitor_id, party_size,
                      preference_rank=None):
    payload = {"account_id": visitor_id, "party_size": party_size}
    if preference_rank is not None:
        payload["preference_rank"] = preference_rank
    return _ok(client.post(f"/v1/lottery-draws/{draw_id}/applications",
                           role="visitor", user_id=visitor_id, json=payload))


def run_draw(client: ApiClient, draw_id, pa_id):
    return _ok(client.post(f"/v1/lottery-draws/{draw_id}/draw",
                           role="park_admin", user_id=pa_id))


def get_campsite_version(client: ApiClient, campsite_id, as_user_id, role="visitor"):
    site = _ok(client.get(f"/v1/campsites/{campsite_id}", role=role, user_id=as_user_id))
    return site["version"]


def join_waitlist(client: ApiClient, campsite_id, visitor_id, check_in,
                  check_out, party_size, expected_campsite_version):
    payload = {"campsite_id": campsite_id, "account_id": visitor_id,
               "check_in": check_in, "check_out": check_out,
               "party_size": party_size,
               "expected_campsite_version": expected_campsite_version}
    return _ok(client.post("/v1/waitlist-entries", role="visitor",
                           user_id=visitor_id, json=payload))
