"""Composite state builders.

The harness restarts the server and empties the database before every single
test, so nothing here may assume pre-existing rows: each builder drives the
public endpoints from an empty database and returns the resulting resources.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    DIRECTOR_HEADERS,
    FINANCE_HEADERS,
    REGISTRAR_HEADERS,
    guardian_headers,
    panelist_headers,
)

SEASON_LADDER = ["PLANNING", "AUDITIONS_OPEN", "PLACEMENT", "IN_SEASON", "CLOSED"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

def set_clock(api: ApiClient, current_utc: str = C.FIXTURE_CLOCK) -> str:
    """Move the logical clock and return the instant now in effect."""
    response = api.set_clock(F.clock_payload(current_utc), DIRECTOR_HEADERS)
    validate_success(response)
    return current_utc


# --------------------------------------------------------------------------
# Single-entity builders
# --------------------------------------------------------------------------

def create_season(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_season(F.season_payload(**overrides), DIRECTOR_HEADERS)
    return validate_success(response, 201)


def create_ensemble(api: ApiClient, season_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_ensemble(
        F.ensemble_payload(season_id, **overrides), DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def create_section_quota(api: ApiClient, ensemble_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_section_quota(
        F.section_quota_payload(ensemble_id, **overrides), DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def create_member(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_member(F.member_payload(**overrides), REGISTRAR_HEADERS)
    return validate_success(response, 201)


def create_panelist(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_panelist(F.panelist_payload(**overrides), DIRECTOR_HEADERS)
    return validate_success(response, 201)


def create_panelists(
    api: ApiClient,
    count: int = 3,
    instrument_expertise: str = "CELLO",
    **overrides: Any,
) -> List[Dict[str, Any]]:
    """Register `count` adjudicators all sharing one instrument expertise."""
    panelists = []
    for index in range(count):
        panelists.append(
            create_panelist(
                api,
                display_name=f"Adjudicator {index + 1}",
                instrument_expertise=instrument_expertise,
                **overrides,
            )
        )
    return panelists


def create_audition_slot(
    api: ApiClient, season_id: str, panelist_ids: Sequence[str], **overrides: Any
) -> Dict[str, Any]:
    response = api.create_audition_slot(
        F.audition_slot_payload(season_id, list(panelist_ids), **overrides),
        REGISTRAR_HEADERS,
    )
    return validate_success(response, 201)


def create_audition(
    api: ApiClient, member_id: str, season_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_audition(
        F.audition_payload(member_id, season_id, **overrides), REGISTRAR_HEADERS
    )
    return validate_success(response, 201)


def create_ensemble_event(api: ApiClient, ensemble_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.create_ensemble_event(
        F.ensemble_event_payload(ensemble_id, **overrides), DIRECTOR_HEADERS
    )
    return validate_success(response, 201)


def create_participation(api: ApiClient, event_id: str, member_id: str) -> Dict[str, Any]:
    response = api.create_event_participation(
        F.participation_payload(event_id, member_id), REGISTRAR_HEADERS
    )
    return validate_success(response, 201)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def read_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return validate_success(api.get_season(season_id, DIRECTOR_HEADERS))


def read_ensemble(api: ApiClient, ensemble_id: str) -> Dict[str, Any]:
    return validate_success(api.get_ensemble(ensemble_id, DIRECTOR_HEADERS))


def read_section_quota(api: ApiClient, quota_id: str) -> Dict[str, Any]:
    return validate_success(api.get_section_quota(quota_id, DIRECTOR_HEADERS))


def read_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return validate_success(api.get_member(member_id, REGISTRAR_HEADERS))


def read_audition(api: ApiClient, audition_id: str) -> Dict[str, Any]:
    return validate_success(api.get_audition(audition_id, DIRECTOR_HEADERS))


def read_audition_slot(api: ApiClient, slot_id: str) -> Dict[str, Any]:
    return validate_success(api.get_audition_slot(slot_id, REGISTRAR_HEADERS))


def read_placement(api: ApiClient, placement_id: str) -> Dict[str, Any]:
    return validate_success(api.get_placement(placement_id, DIRECTOR_HEADERS))


def read_seat(api: ApiClient, seat_id: str) -> Dict[str, Any]:
    return validate_success(api.get_seat_assignment(seat_id, DIRECTOR_HEADERS))


def read_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return validate_success(api.get_tuition_account(account_id, FINANCE_HEADERS))


def read_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return validate_success(api.get_ensemble_event(event_id, DIRECTOR_HEADERS))


def read_participation(api: ApiClient, participation_id: str) -> Dict[str, Any]:
    return validate_success(api.get_event_participation(participation_id, DIRECTOR_HEADERS))


def ensemble_version(api: ApiClient, ensemble_id: str) -> int:
    return read_ensemble(api, ensemble_id)["version"]


def season_version(api: ApiClient, season_id: str) -> int:
    return read_season(api, season_id)["version"]


def list_all(api_method, headers: Dict[str, str], **filters: Any) -> List[Dict[str, Any]]:
    """Fetch a full list page (100 rows) with optional equality filters."""
    params: Dict[str, Any] = {"limit": C.MAX_LIMIT, "offset": 0}
    params.update({k: v for k, v in filters.items() if v is not None})
    response = api_method(headers, params=params)
    return get_success_data(response)


def list_seats(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return list_all(api.list_seat_assignments, DIRECTOR_HEADERS, **filters)


def list_accounts(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return list_all(api.list_tuition_accounts, FINANCE_HEADERS, **filters)


def list_placements(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return list_all(api.list_placements, DIRECTOR_HEADERS, **filters)


def list_sheets(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return list_all(api.list_panel_scores, DIRECTOR_HEADERS, **filters)


def list_participations(api: ApiClient, **filters: Any) -> List[Dict[str, Any]]:
    return list_all(api.list_event_participations, DIRECTOR_HEADERS, **filters)


def sole_account(api: ApiClient, member_id: str, season_id: str) -> Dict[str, Any]:
    """The one tuition account for a musician and season, discovered by filter."""
    rows = list_accounts(api, member_id=member_id, season_id=season_id)
    assert len(rows) == 1, f"expected exactly one tuition account, got {len(rows)}"
    return rows[0]


def sole_active_seat(api: ApiClient, member_id: str) -> Dict[str, Any]:
    rows = [
        row
        for row in list_seats(api, member_id=member_id)
        if row["status"] == "ACTIVE"
    ]
    assert len(rows) == 1, f"expected exactly one ACTIVE chair, got {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------
# Workflow steps
# --------------------------------------------------------------------------

def advance_season(api: ApiClient, season_id: str, to_status: str) -> Dict[str, Any]:
    response = api.advance_season_status(
        season_id, F.advance_status_payload(to_status), DIRECTOR_HEADERS
    )
    return validate_success(response)


def advance_season_to(api: ApiClient, season_id: str, target_status: str) -> Dict[str, Any]:
    """Walk the phase ladder one rung at a time up to `target_status`."""
    season = read_season(api, season_id)
    while season["status"] != target_status:
        current_index = SEASON_LADDER.index(season["status"])
        season = advance_season(api, season_id, SEASON_LADDER[current_index + 1])
    return season


def schedule_audition(api: ApiClient, audition_id: str, slot_id: str) -> Dict[str, Any]:
    response = api.schedule_audition(
        audition_id, F.schedule_payload(slot_id), REGISTRAR_HEADERS
    )
    return validate_success(response)


def submit_sheet(
    api: ApiClient, audition_id: str, panelist_id: str, **rubric: Any
) -> Dict[str, Any]:
    response = api.submit_panel_score(
        audition_id,
        F.panel_score_payload(panelist_id, **rubric),
        panelist_headers(panelist_id),
    )
    return validate_success(response, 201)


def submit_uniform_sheets(
    api: ApiClient,
    audition_id: str,
    panelists: Sequence[Dict[str, Any]],
    value: int = 20,
) -> List[Dict[str, Any]]:
    """One sheet per adjudicator, all four rubric integers equal to `value`.

    A uniform sheet weights out to exactly four times `value`, because the four
    rubric weights total 4.0.
    """
    sheets = []
    for panelist in panelists:
        sheets.append(
            submit_sheet(
                api,
                audition_id,
                panelist["id"],
                tone_score=value,
                rhythm_score=value,
                intonation_score=value,
                sight_reading_score=value,
            )
        )
    return sheets


def adjudicate(api: ApiClient, audition_id: str) -> Dict[str, Any]:
    response = api.adjudicate_audition(audition_id, {}, DIRECTOR_HEADERS)
    return validate_success(response)


def create_placement(
    api: ApiClient,
    audition_id: str,
    ensemble_id: str,
    offer_kind: str = "OFFER",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a placement, reading the ensemble's current version for the guard."""
    payload = F.placement_payload(
        audition_id,
        ensemble_id,
        ensemble_version(api, ensemble_id),
        offer_kind=offer_kind,
        **overrides,
    )
    response = api.create_placement(payload, DIRECTOR_HEADERS)
    return validate_success(response, 201)


def accept_placement(
    api: ApiClient, placement_id: str, member_id: str, **body: Any
) -> Dict[str, Any]:
    response = api.accept_placement(
        placement_id, F.accept_payload(**body), guardian_headers(member_id)
    )
    return validate_success(response)


def record_attendance(
    api: ApiClient,
    participation_id: str,
    attendance_status: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api.record_attendance(
        participation_id,
        F.attendance_payload(attendance_status),
        headers or REGISTRAR_HEADERS,
    )
    return validate_success(response)


def review_eligibility(api: ApiClient, participation_id: str) -> Dict[str, Any]:
    response = api.review_eligibility(
        participation_id, F.eligibility_review_payload(), DIRECTOR_HEADERS
    )
    return validate_success(response)


def rotate_chairs(api: ApiClient, quota_id: str, ensemble_id: str) -> Dict[str, Any]:
    response = api.rotate_chairs(
        quota_id,
        F.rotate_chairs_payload(ensemble_version(api, ensemble_id)),
        DIRECTOR_HEADERS,
    )
    return validate_success(response)


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------

def open_season_with_ensemble(
    api: ApiClient,
    clock: str = C.FIXTURE_CLOCK,
    season_overrides: Optional[Dict[str, Any]] = None,
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A season in `AUDITIONS_OPEN` owning one ensemble with one section."""
    set_clock(api, clock)
    season = create_season(api, **(season_overrides or {}))
    ensemble = create_ensemble(api, season["id"], **(ensemble_overrides or {}))
    quota = create_section_quota(api, ensemble["id"], **(quota_overrides or {}))
    season = advance_season(api, season["id"], "AUDITIONS_OPEN")
    return {"clock": clock, "season": season, "ensemble": ensemble, "quota": quota}


def scored_audition(
    api: ApiClient,
    clock: str = C.FIXTURE_CLOCK,
    instrument: str = "CELLO",
    score_value: int = 20,
    panelist_count: int = 3,
    season_overrides: Optional[Dict[str, Any]] = None,
    ensemble_overrides: Optional[Dict[str, Any]] = None,
    quota_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    slot_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An audition sitting in `SCORED` after a full quorum of uniform sheets."""
    quota_defaults = {"instrument": instrument}
    quota_defaults.update(quota_overrides or {})
    ctx = open_season_with_ensemble(
        api,
        clock=clock,
        season_overrides=season_overrides,
        ensemble_overrides=ensemble_overrides,
        quota_overrides=quota_defaults,
    )
    member_defaults = {"primary_instrument": instrument}
    member_defaults.update(member_overrides or {})
    member = create_member(api, **member_defaults)
    panelists = create_panelists(
        api, count=panelist_count, instrument_expertise=instrument
    )
    slot_defaults = {"instrument_focus": instrument}
    slot_defaults.update(slot_overrides or {})
    slot = create_audition_slot(
        api,
        ctx["season"]["id"],
        [p["id"] for p in panelists],
        **slot_defaults,
    )
    audition = create_audition(api, member["id"], ctx["season"]["id"])
    schedule_audition(api, audition["id"], slot["id"])
    quorum = slot["quorum_required"]
    sheets = submit_uniform_sheets(api, audition["id"], panelists[:quorum], score_value)
    ctx.update(
        {
            "member": member,
            "panelists": panelists,
            "slot": slot,
            "audition": read_audition(api, audition["id"]),
            "sheets": sheets,
        }
    )
    return ctx


def adjudicated_audition(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A `SCORED` audition closed by the director, so it carries a tier band."""
    ctx = scored_audition(api, **kwargs)
    ctx["audition"] = adjudicate(api, ctx["audition"]["id"])
    return ctx


def placement_offer(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A season in `PLACEMENT` holding one `OFFERED` placement."""
    ctx = adjudicated_audition(api, **kwargs)
    ctx["season"] = advance_season(api, ctx["season"]["id"], "PLACEMENT")
    ctx["placement"] = create_placement(
        api, ctx["audition"]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    ctx["ensemble"] = read_ensemble(api, ctx["ensemble"]["id"])
    return ctx


def accepted_placement(
    api: ApiClient, instrument_loan_requested: Optional[bool] = None, **kwargs: Any
) -> Dict[str, Any]:
    """An accepted offer, so a chair and a tuition account both exist."""
    ctx = placement_offer(api, **kwargs)
    body: Dict[str, Any] = {}
    if instrument_loan_requested is not None:
        body["instrument_loan_requested"] = instrument_loan_requested
    ctx["placement"] = accept_placement(
        api, ctx["placement"]["id"], ctx["member"]["id"], **body
    )
    ctx["seat"] = sole_active_seat(api, ctx["member"]["id"])
    ctx["account"] = sole_account(api, ctx["member"]["id"], ctx["season"]["id"])
    ctx["season"] = read_season(api, ctx["season"]["id"])
    ctx["ensemble"] = read_ensemble(api, ctx["ensemble"]["id"])
    ctx["quota"] = read_section_quota(api, ctx["quota"]["id"])
    ctx["member"] = read_member(api, ctx["member"]["id"])
    return ctx
