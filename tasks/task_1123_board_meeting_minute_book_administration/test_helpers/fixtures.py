"""Composite setup helpers for the Board Governance API.

These encapsulate multi-step preconditions shared across tests. Every helper
uses the lenient get_success_data validator so setup failures surface as
clear "Setup failed" errors rather than assertion noise.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    DEFAULT_MEETING_START,
    DEFAULT_TERM_END,
    DEFAULT_TERM_START,
)
from .factories import (
    create_agenda_item_payload,
    create_attendance_payload,
    create_board_package_payload,
    create_bylaws_payload,
    create_committee_membership_payload,
    create_committee_payload,
    create_conflict_disclosure_payload,
    create_corporation_payload,
    create_director_payload,
    create_meeting_payload,
    create_package_document_payload,
    create_resolution_payload,
    create_vote_record_payload,
)
from .test_users import TEST_USERS, make_chair_headers, make_director_headers

SECRETARY = TEST_USERS["secretary_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: corporation / bylaws / director building blocks
# ---------------------------------------------------------------------------


def create_corporation(name: str = "Corp", incorporation_state: str = "DE") -> Dict[str, Any]:
    resp = api_client.create_corporation(
        create_corporation_payload(name=name, incorporation_state=incorporation_state), SECRETARY
    )
    return get_success_data(resp)


def create_draft_bylaws(corporation_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_bylaws(create_bylaws_payload(corporation_id, **overrides), SECRETARY)
    return get_success_data(resp)


def adopt_bylaws(bylaws_id: str, expected_corporation_version: int) -> Dict[str, Any]:
    resp = api_client.adopt_bylaws(
        bylaws_id, {"expected_corporation_version": expected_corporation_version}, SECRETARY
    )
    return get_success_data(resp)


def setup_corporation_with_adopted_bylaws(
    name: str = "Corp", incorporation_state: str = "DE", **bylaws_overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a corporation and an ADOPTED bylaws. Returns (corporation, bylaws).

    The corporation returned is re-fetched after adoption so its `version`
    reflects the adoption bump (creation version + 1).
    """
    corp = create_corporation(name=name, incorporation_state=incorporation_state)
    bylaws = create_draft_bylaws(corp["id"], **bylaws_overrides)
    adopt_bylaws(bylaws["id"], corp["version"])
    corp_after = get_success_data(api_client.get_corporation(corp["id"], SECRETARY))
    bylaws_after = get_success_data(api_client.get_bylaws(bylaws["id"], SECRETARY))
    return corp_after, bylaws_after


def add_director(
    corporation_id: str,
    full_name: str,
    email: str,
    term_start: str = DEFAULT_TERM_START,
    term_end: str = DEFAULT_TERM_END,
    **overrides,
) -> Dict[str, Any]:
    resp = api_client.create_director(
        create_director_payload(
            corporation_id, full_name, email, term_start=term_start, term_end=term_end, **overrides
        ),
        SECRETARY,
    )
    return get_success_data(resp)


def add_directors(corporation_id: str, count: int, email_prefix: str = "d") -> List[Dict[str, Any]]:
    """Appoint `count` directors with predictable names d1..dN / d1@x.com..dN@x.com."""
    out: List[Dict[str, Any]] = []
    for i in range(1, count + 1):
        out.append(add_director(corporation_id, f"D{i}", f"{email_prefix}{i}@x.com"))
    return out


def setup_corporation_with_directors(
    num_directors: int,
    name: str = "Corp",
    incorporation_state: str = "DE",
    **bylaws_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create corporation, adopt bylaws, appoint N directors.

    Returns (corporation_after_adoption, bylaws, [director, ...]).
    """
    corp, bylaws = setup_corporation_with_adopted_bylaws(
        name=name, incorporation_state=incorporation_state, **bylaws_overrides
    )
    directors = add_directors(corp["id"], num_directors)
    return corp, bylaws, directors


# ---------------------------------------------------------------------------
# Tier 2: committees
# ---------------------------------------------------------------------------


def create_committee(
    corporation_id: str,
    name: str = "C",
    committee_type: str = "SPECIAL",
    charter_text: str = "charter",
    quorum_fixed_count: int = 1,
) -> Dict[str, Any]:
    resp = api_client.create_committee(
        create_committee_payload(
            corporation_id,
            name,
            committee_type,
            charter_text=charter_text,
            quorum_fixed_count=quorum_fixed_count,
        ),
        SECRETARY,
    )
    return get_success_data(resp)


def activate_committee(committee_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_committee(committee_id, SECRETARY))


def setup_active_committee(
    corporation_id: str,
    name: str = "C",
    committee_type: str = "SPECIAL",
    quorum_fixed_count: int = 1,
) -> Dict[str, Any]:
    cm = create_committee(
        corporation_id,
        name=name,
        committee_type=committee_type,
        quorum_fixed_count=quorum_fixed_count,
    )
    return activate_committee(cm["id"])


def add_membership(
    committee_id: str,
    director_id: str,
    committee_role: str = "MEMBER",
    term_start: str = "2026-02-01T00:00:00Z",
    term_end: str = "2028-02-01T00:00:00Z",
) -> Dict[str, Any]:
    resp = api_client.create_committee_membership(
        create_committee_membership_payload(
            committee_id, director_id, committee_role, term_start=term_start, term_end=term_end
        ),
        SECRETARY,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: meetings / attendance / resolutions / agenda
# ---------------------------------------------------------------------------


def schedule_meeting(
    corporation_id: str,
    chair_director_id: str,
    meeting_type: str = "REGULAR",
    scheduled_start: str = DEFAULT_MEETING_START,
    duration_minutes: int = 60,
    location_or_medium: str = "Boardroom",
) -> Dict[str, Any]:
    resp = api_client.create_meeting(
        create_meeting_payload(
            corporation_id,
            chair_director_id,
            meeting_type=meeting_type,
            scheduled_start=scheduled_start,
            duration_minutes=duration_minutes,
            location_or_medium=location_or_medium,
        ),
        SECRETARY,
    )
    return get_success_data(resp)


def send_notices(meeting_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.send_notices(meeting_id, SECRETARY))


def schedule_noticed_meeting(
    corporation_id: str,
    chair_director_id: str,
    meeting_type: str = "REGULAR",
    scheduled_start: str = DEFAULT_MEETING_START,
    duration_minutes: int = 60,
) -> Dict[str, Any]:
    """Create a meeting and send notices. Returns the NOTICED meeting."""
    m = schedule_meeting(
        corporation_id,
        chair_director_id,
        meeting_type=meeting_type,
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    return send_notices(m["id"])


def record_attendance(
    meeting_id: str,
    director_id: str,
    mode: str = "IN_PERSON",
    proxy_holder_director_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_attendance_payload(meeting_id, director_id, mode)
    if proxy_holder_director_id is not None:
        payload["proxy_holder_director_id"] = proxy_holder_director_id
    resp = api_client.create_attendance_record(payload, SECRETARY)
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SECRETARY))


def convene_meeting(meeting_id: str, chair_director_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.convene_meeting(meeting_id, make_chair_headers(chair_director_id)))


def adjourn_meeting(meeting_id: str, chair_director_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.adjourn_meeting(meeting_id, make_chair_headers(chair_director_id)))


def setup_in_session_meeting(
    corporation_id: str,
    chair_director_id: str,
    present_director_ids: List[str],
    meeting_type: str = "REGULAR",
    scheduled_start: str = DEFAULT_MEETING_START,
    duration_minutes: int = 60,
    convene_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a meeting, send notices, record attendance for the listed
    directors (IN_PERSON), advance the clock to the start, and convene.

    Returns the IN_SESSION meeting.
    """
    m = schedule_noticed_meeting(
        corporation_id,
        chair_director_id,
        meeting_type=meeting_type,
        scheduled_start=scheduled_start,
        duration_minutes=duration_minutes,
    )
    for did in present_director_ids:
        record_attendance(m["id"], did, "IN_PERSON")
    set_clock(convene_clock or scheduled_start)
    return convene_meeting(m["id"], chair_director_id)


def create_meeting_resolution(
    corporation_id: str,
    meeting_id: str,
    resolution_type: str = "ORDINARY",
    title: str = "R",
    text: str = "t",
    related_party: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_resolution_payload(
        corporation_id,
        "MEETING",
        resolution_type,
        title,
        text,
        meeting_id=meeting_id,
    )
    if related_party is not None:
        payload["related_party"] = related_party
    resp = api_client.create_resolution(payload, SECRETARY)
    return get_success_data(resp)


def table_resolution(resolution_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.table_resolution(resolution_id, SECRETARY))


def open_vote_as_chair(resolution_id: str, chair_director_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_vote(resolution_id, make_chair_headers(chair_director_id)))


def close_vote_as_chair(resolution_id: str, chair_director_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_vote(resolution_id, make_chair_headers(chair_director_id)))


def setup_vote_open_resolution(
    corporation_id: str,
    meeting_id: str,
    chair_director_id: str,
    resolution_type: str = "ORDINARY",
    title: str = "R",
    text: str = "t",
    related_party: Optional[str] = None,
) -> Dict[str, Any]:
    """Create + table + open the vote on a MEETING resolution. Returns VOTE_OPEN resolution."""
    r = create_meeting_resolution(
        corporation_id, meeting_id, resolution_type=resolution_type, title=title, text=text,
        related_party=related_party,
    )
    table_resolution(r["id"])
    return open_vote_as_chair(r["id"], chair_director_id)


def cast_ballot(resolution_id: str, director_id: str, vote: str) -> Dict[str, Any]:
    resp = api_client.create_vote_record(
        create_vote_record_payload(resolution_id, "MEETING_BALLOT", vote),
        make_director_headers(director_id),
    )
    return get_success_data(resp)


def sign_consent(resolution_id: str, director_id: str, vote: str = "FOR") -> Dict[str, Any]:
    resp = api_client.create_vote_record(
        create_vote_record_payload(resolution_id, "WRITTEN_CONSENT", vote),
        make_director_headers(director_id),
    )
    return get_success_data(resp)


def create_agenda_item(
    meeting_id: str,
    title: str,
    order_index: int,
    proposed_by_director_id: str,
    resolution_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_agenda_item_payload(meeting_id, title, order_index, proposed_by_director_id)
    if resolution_id is not None:
        payload["resolution_id"] = resolution_id
    resp = api_client.create_agenda_item(payload, SECRETARY)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: written consent
# ---------------------------------------------------------------------------


def create_consent_resolution(
    corporation_id: str,
    title: str = "R",
    text: str = "t",
    resolution_type: str = "ORDINARY",
    related_party: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_resolution_payload(corporation_id, "WRITTEN_CONSENT", resolution_type, title, text)
    if related_party is not None:
        payload["related_party"] = related_party
    resp = api_client.create_resolution(payload, SECRETARY)
    return get_success_data(resp)


def setup_circulating_consent(
    corporation_id: str,
    title: str = "R",
    text: str = "t",
    related_party: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a WRITTEN_CONSENT resolution and circulate it. Returns CIRCULATING resolution."""
    r = create_consent_resolution(corporation_id, title=title, text=text, related_party=related_party)
    return get_success_data(api_client.circulate_consent(r["id"], SECRETARY))


def file_disclosure(
    director_id: str,
    corporation_id: str,
    related_party: str = "Acme",
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: str = "2026-12-31T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    resp = api_client.create_conflict_disclosure(
        create_conflict_disclosure_payload(
            director_id,
            corporation_id,
            related_party,
            effective_from=effective_from,
            effective_to=effective_to,
            **overrides,
        ),
        SECRETARY,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: minutes lifecycle / minute book / audit
# ---------------------------------------------------------------------------


def get_minutes_for_meeting(meeting_id: str) -> Dict[str, Any]:
    """Fetch the single auto-created minutes row for an adjourned meeting."""
    data, _meta = _list_minutes(meeting_id)
    assert len(data) == 1, f"expected exactly 1 minutes row for meeting {meeting_id}, got {len(data)}"
    return data[0]


def _list_minutes(meeting_id: str):
    resp = api_client.list_minutes(SECRETARY, params={"meeting_id": meeting_id})
    body = get_success_data(resp)
    # list endpoints: get_success_data returns envelope payload — use validate_paginated form
    from prd_bench_local_runner.testing import validate_paginated

    data, meta = validate_paginated(resp)
    return data, meta


def setup_adjourned_meeting_with_minutes(
    corporation_id: str,
    chair_director_id: str,
    present_director_ids: List[str],
    scheduled_start: str = DEFAULT_MEETING_START,
    convene_clock: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create + notice + convene + adjourn a meeting. Returns (meeting, minutes_draft)."""
    m = setup_in_session_meeting(
        corporation_id,
        chair_director_id,
        present_director_ids,
        scheduled_start=scheduled_start,
        convene_clock=convene_clock,
    )
    adjourn_meeting(m["id"], chair_director_id)
    mn = get_minutes_for_meeting(m["id"])
    return m, mn


def setup_minutes_in_book(
    corporation_id: str,
    chair_director_id: str,
    present_director_ids: List[str],
    content: str = "body of minutes",
    scheduled_start: str = DEFAULT_MEETING_START,
    convene_clock: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full lifecycle through ENTERED_IN_BOOK. Returns (meeting, minutes)."""
    m, mn = setup_adjourned_meeting_with_minutes(
        corporation_id,
        chair_director_id,
        present_director_ids,
        scheduled_start=scheduled_start,
        convene_clock=convene_clock,
    )
    api_client.circulate_minutes(mn["id"], {"content": content}, SECRETARY)
    api_client.approve_minutes(mn["id"], make_chair_headers(chair_director_id))
    resp = api_client.enter_book_minutes(mn["id"], SECRETARY)
    mn_final = get_success_data(resp)
    return m, mn_final


# ---------------------------------------------------------------------------
# Tier 6: board packages
# ---------------------------------------------------------------------------


def create_package(meeting_id: str) -> Dict[str, Any]:
    resp = api_client.create_board_package(create_board_package_payload(meeting_id), SECRETARY)
    return get_success_data(resp)


def add_document(package_id: str, title: str, content_ref: str, tier: str) -> Dict[str, Any]:
    resp = api_client.create_package_document(
        create_package_document_payload(package_id, title, content_ref, tier), SECRETARY
    )
    return get_success_data(resp)
