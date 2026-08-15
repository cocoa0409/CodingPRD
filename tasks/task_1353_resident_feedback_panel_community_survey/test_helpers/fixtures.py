"""Composite setup helpers for the feedback panel API.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses get_success_data() so a setup
failure surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_cell_payload, create_panelist_payload, create_instrument_payload,
    create_translation_payload, create_wave_payload, create_invitation_payload,
    create_response_payload, create_snapshot_payload, create_publication_payload,
    create_commitment_payload, create_privacy_hold_payload,
)
from .test_users import TEST_USERS, make_analyst_headers, make_liaison_headers, make_privacy_headers

PM = TEST_USERS["panel_manager"]
SD = TEST_USERS["survey_designer"]
DA = TEST_USERS["data_analyst"]
IC = TEST_USERS["incentive_clerk"]
PO = TEST_USERS["privacy_officer"]


def _ok(resp, step: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or (resp.status_code >= 400):
        raise AssertionError(f"Setup failed at step '{step}': status={resp.status_code} body={resp.text}")
    return data


def set_clock(to_iso8601: str):
    """Advance the logical clock (PanelManager-only capability)."""
    _ok(api.set_clock(to_iso8601, PM), f"set_clock({to_iso8601})")


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_cell(target_size=5, **overrides):
    payload = create_cell_payload(target_size=target_size, **overrides)
    return _ok(api.create_panel_cell(payload, PM), "create_cell")


def create_panelist(age_band="AGE_18_29", district="D1", tenure_bucket="RENTER",
                    preferred_locale="en", **overrides):
    payload = create_panelist_payload(
        age_band=age_band, district=district, tenure_bucket=tenure_bucket,
        preferred_locale=preferred_locale, **overrides)
    return _ok(api.create_panelist(payload, PM), "create_panelist")


def create_enrolled_panelist(cell=None, cell_kwargs=None, **panelist_kwargs):
    """Cell + registered applicant + enroll. Returns (cell, panelist)."""
    if cell is None:
        cell = create_cell(**(cell_kwargs or {}))
    triple = {
        "age_band": cell["age_band"], "district": cell["district"],
        "tenure_bucket": cell["tenure_bucket"],
    }
    triple.update({k: v for k, v in panelist_kwargs.items()
                   if k in ("age_band", "district", "tenure_bucket")})
    panelist = create_panelist(**triple,
                               **{k: v for k, v in panelist_kwargs.items()
                                  if k not in triple})
    enrolled = _ok(api.enroll_panelist(panelist["id"], PM), "enroll_panelist")
    return cell, enrolled


def create_locked_instrument(title="Community Survey", question_count=5,
                             required_locales=("en",), base_locale="en",
                             extra_certified_locales=()):
    """Instrument walked DRAFT -> IN_REVIEW -> APPROVED -> LOCKED with a
    CERTIFIED translation for every required locale. Returns the instrument."""
    instr = _ok(api.create_instrument(
        create_instrument_payload(title=title, question_count=question_count,
                                  required_locales=list(required_locales),
                                  base_locale=base_locale), SD), "create_instrument")
    _ok(api.submit_instrument_review(instr["id"], SD), "submit_review")
    for locale in required_locales:
        tr = _ok(api.create_translation(
            create_translation_payload(instr["id"], locale=locale), SD),
            f"create_translation[{locale}]")
        _ok(api.certify_translation(tr["id"], SD), f"certify[{locale}]")
    _ok(api.approve_instrument(instr["id"], SD), "approve_instrument")
    return _ok(api.lock_instrument(instr["id"], SD), "lock_instrument")


def create_wave(instrument_id, **overrides):
    return _ok(api.create_wave(create_wave_payload(instrument_id, **overrides), PM),
               "create_wave")


def create_armed_wave(instrument_id, arm_at=None, **overrides):
    wave = create_wave(instrument_id, **overrides)
    if arm_at is not None:
        set_clock(arm_at)
    _ok(api.arm_wave(wave["id"], PM), "arm_wave")
    return _ok(api.get_wave(wave["id"], PM), "get_wave")


def create_fielding_wave(instrument_id, fielding_now=None, **overrides):
    """Wave walked DRAFT -> ARMED -> FIELDING. Clock is parked at fielding_now."""
    wave = create_armed_wave(instrument_id, **overrides)
    set_clock(fielding_now or TEST_DEFAULTS["FIELDING_NOW"])
    _ok(api.open_fielding(wave["id"], PM), "open_fielding")
    return _ok(api.get_wave(wave["id"], PM), "get_wave")


def dispatch_invitation(wave_id, panelist_id):
    return _ok(api.create_invitation(create_invitation_payload(wave_id, panelist_id), PM),
               "create_invitation")


def submit_response(invitation_id, completeness_pct=100, completion_seconds=300,
                    answers_payload=None):
    payload = create_response_payload(
        invitation_id, completeness_pct=completeness_pct,
        completion_seconds=completion_seconds,
        answers_payload=answers_payload or {"q1": 4})
    return _ok(api.create_response(payload, PM), "create_response")


def accept_response(response_id, headers=None):
    return _ok(api.accept_response(response_id, headers or DA), "accept_response")


def get_award_for_response(response_id):
    """Exactly one award is minted per response; fetch it via the list filter."""
    rows, meta = _list(api.list_awards(IC, params={"response_id": response_id}))
    assert len(rows) == 1, f"Setup failed: expected exactly one award for response {response_id}, got {len(rows)}"
    return rows[0]


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 2: composite scenario — cell + panelist + locked instrument + fielding wave
# ---------------------------------------------------------------------------

def setup_fielding_scenario(target_size=5, base_incentive_cents=None,
                            pool_total_cents=None, preferred_locale="en",
                            min_response_rate=None, fielding_now=None,
                            opens_at=None, closes_at=None):
    """Cell + one ACTIVE panelist + locked instrument + FIELDING wave.
    Returns dict(cell, panelist, instrument, wave)."""
    cell = create_cell(target_size=target_size)
    panelist = create_panelist()
    enrolled = _ok(api.enroll_panelist(panelist["id"], PM), "enroll")
    instr = create_locked_instrument()
    wave_kwargs = {}
    if base_incentive_cents is not None:
        wave_kwargs["base_incentive_cents"] = base_incentive_cents
    if pool_total_cents is not None:
        wave_kwargs["incentive_pool_total_cents"] = pool_total_cents
    if min_response_rate is not None:
        wave_kwargs["min_response_rate"] = min_response_rate
    if opens_at is not None:
        wave_kwargs["opens_at"] = opens_at
    if closes_at is not None:
        wave_kwargs["closes_at"] = closes_at
    wave = create_fielding_wave(instr["id"], fielding_now=fielding_now, **wave_kwargs)
    if preferred_locale != "en":
        panelist = create_panelist(preferred_locale=preferred_locale)
        enrolled = _ok(api.enroll_panelist(panelist["id"], PM), "enroll")
    return {"cell": cell, "panelist": enrolled, "instrument": instr, "wave": wave}


def setup_closed_wave_with_accepted(num_respondents=1, cell_target=5,
                                   fielding_now=None, after_close=None):
    """One cell, N ACTIVE panelists in it, locked instrument, FIELDING wave,
    all invited, all responded (100% / 300s) and ACCEPTED, wave closed past
    closes_at. Returns dict(cell, panelists, instrument, wave, responses, awards).

    Sends are staggered in batches of CONTACT_CAP (3) with an 8-day gap: PRD
    §3.5 caps a cell at 3 invitations within any trailing 7-day window,
    inclusive of both endpoints."""
    from datetime import datetime, timedelta
    cell = create_cell(target_size=cell_target)
    panelists = []
    for _ in range(num_respondents):
        p = create_panelist()
        panelists.append(_ok(api.enroll_panelist(p["id"], PM), "enroll"))
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], fielding_now=fielding_now)
    base = datetime.fromisoformat(
        (fielding_now or TEST_DEFAULTS["FIELDING_NOW"]).replace("Z", "+00:00"))
    last_send = base
    responses, awards = [], []
    for idx, p in enumerate(panelists):
        if idx and idx % 3 == 0:
            last_send = base + timedelta(days=8 * (idx // 3))
            set_clock(last_send.strftime("%Y-%m-%dT%H:%M:%SZ"))
        inv = dispatch_invitation(wave["id"], p["id"])
        r = submit_response(inv["id"])
        accept_response(r["id"])
        responses.append(r)
        awards.append(get_award_for_response(r["id"]))
    close_at = datetime.fromisoformat(
        (after_close or TEST_DEFAULTS["AFTER_CLOSE"]).replace("Z", "+00:00"))
    if close_at < last_send:
        close_at = last_send  # never move the logical clock backward
    set_clock(close_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    wave = _ok(api.close_wave(wave["id"], PM), "close_wave")
    return {"cell": cell, "panelists": panelists, "instrument": instr,
            "wave": wave, "responses": responses, "awards": awards}


def current_wave_version(wave_id):
    return _ok(api.get_wave(wave_id, DA), "get_wave")["version"]


def create_snapshot(wave_id, method="POST_STRAT", expected_wave_version=None,
                    headers=None):
    if expected_wave_version is None:
        expected_wave_version = current_wave_version(wave_id)
    return _ok(api.create_weight_snapshot(
        wave_id, create_snapshot_payload(expected_wave_version, method=method),
        headers or DA), "create_weight_snapshot")


def create_finalized_snapshot(wave_id, method="POST_STRAT", finalizer_user_id="analyst-1"):
    snap = create_snapshot(wave_id, method=method)
    return _ok(api.finalize_weight_snapshot(
        snap["id"], make_analyst_headers(finalizer_user_id)), "finalize_snapshot")


def setup_published_publication(k_threshold=1, publisher_user_id="privacy-1",
                                finalizer_user_id="analyst-1"):
    """Full pipeline through a PUBLISHED publication. Returns
    dict(cell, panelist, wave, response, snapshot, publication)."""
    s = setup_closed_wave_with_accepted(num_respondents=1)
    snap = create_finalized_snapshot(s["wave"]["id"], finalizer_user_id=finalizer_user_id)
    pub = _ok(api.create_publication(
        create_publication_payload(s["wave"]["id"], snap["id"], k_threshold=k_threshold),
        DA), "create_publication")
    pub = _ok(api.publish_publication(pub["id"], make_privacy_headers(publisher_user_id)),
              "publish_publication")
    return {"cell": s["cell"], "panelist": s["panelists"][0], "wave": s["wave"],
            "response": s["responses"][0], "snapshot": snap, "publication": pub}


def create_commitment(publication_id, department_name="DEPT_TRANSPORT",
                      summary="Act on findings", due_at="2026-09-01T00:00:00Z"):
    payload = create_commitment_payload(
        publication_id, department_name=department_name, summary=summary, due_at=due_at)
    return _ok(api.create_commitment(payload, make_liaison_headers(department_name)),
               "create_commitment")
