"""Composite setup helpers.

Every fixture builds the state it needs from scratch using only PRD §4 endpoints.
The harness restarts the API server before every pytest test, so each test starts
against an empty database.
"""
from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_asset_payload,
    create_clearance_request_payload,
    create_diligence_log_payload,
    create_rights_holder_payload,
    create_round_payload,
    create_takedown_payload,
)
from .test_users import (
    make_certifier_headers,
    make_curator_headers,
    make_ingest_headers,
    make_negotiator_headers,
    make_officer_headers,
    make_payer_headers,
    make_requester_headers,
    make_rights_holder_rep_headers,
)


# Default unique-per-test user ids. Tests should pass their own to isolate.
_COUNTER = [0]


def _uid(prefix: str) -> str:
    _COUNTER[0] += 1
    return f"{prefix}_{_COUNTER[0]}"


# ---------------------------------------------------------------------------
# Tier 1: simple entity builders
# ---------------------------------------------------------------------------


def create_rights_holder(
    legal_name: str = "Holder",
    holder_kind: str = "LABEL",
    mfn_floor_cents: int = 100,
    contact_verified: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "holder_kind": holder_kind,
        "mfn_floor_cents": mfn_floor_cents,
    }
    if contact_verified is not None:
        payload["contact_verified"] = contact_verified
    headers = make_curator_headers(_uid("cur"))
    resp = api_client.create_rights_holder(payload, headers)
    return get_success_data(resp)


def create_asset(
    title: str = "Asset",
    work_kind: str = "FILM_CLIP",
    permitted_media: Optional[list] = None,
    embargo_until: Optional[str] = None,
    rights_holder_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title,
        "work_kind": work_kind,
        "permitted_media": permitted_media or ["STREAMING"],
    }
    if embargo_until is not None:
        payload["embargo_until"] = embargo_until
    if rights_holder_id is not None:
        payload["rights_holder_id"] = rights_holder_id
    headers = make_curator_headers(_uid("cur"))
    resp = api_client.create_asset(payload, headers)
    return get_success_data(resp)


def create_clearance_request(
    asset_id: str,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-09-01T00:00:00Z",
    use_end_at: str = "2026-11-01T00:00:00Z",
    requested_units: int = 1,
    requester_user_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Returns (request_dict, requester_user_id). Caller keeps the user_id for ownership calls."""
    rid = requester_user_id or _uid("req")
    headers = make_requester_headers(rid)
    payload = {
        "media": media,
        "territory": territory,
        "use_start_at": use_start_at,
        "use_end_at": use_end_at,
        "requested_units": requested_units,
    }
    resp = api_client.create_clearance_request(asset_id, payload, headers)
    return get_success_data(resp), rid


def advance_request(request_id: str, expected_version: int) -> Dict[str, Any]:
    headers = make_officer_headers(_uid("off"))
    resp = api_client.advance_clearance_request(request_id, expected_version, headers)
    return get_success_data(resp)


def post_round(
    request_id: str,
    offered_fee_cents: int,
    accept: Optional[bool] = None,
    role: str = "Negotiator",
    user_id: Optional[str] = None,
    holder_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"offered_fee_cents": offered_fee_cents}
    if accept is not None:
        payload["accept"] = accept
    if role == "RightsHolderRep":
        if not holder_id:
            raise ValueError("RightsHolderRep round requires holder_id for entity-backed identity")
        headers = make_rights_holder_rep_headers(holder_id)
    else:
        headers = make_negotiator_headers(user_id or _uid("neg"))
    resp = api_client.post_round(request_id, payload, headers)
    return get_success_data(resp)


def post_round_raw(
    request_id: str,
    payload: Dict[str, Any],
    role: str = "Negotiator",
    user_id: Optional[str] = None,
    holder_id: Optional[str] = None,
):
    """Raw round POST returning the response — used when we expect a non-2xx."""
    if role == "RightsHolderRep":
        if not holder_id:
            raise ValueError("RightsHolderRep round requires holder_id for entity-backed identity")
        headers = make_rights_holder_rep_headers(holder_id)
    else:
        headers = make_negotiator_headers(user_id or _uid("neg"))
    return api_client.post_round(request_id, payload, headers)


def grant_license(request_id: str, grant_fee_cents: int) -> Dict[str, Any]:
    headers = make_officer_headers(_uid("off"))
    resp = api_client.grant_license(request_id, grant_fee_cents, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — holder + asset + request
# ---------------------------------------------------------------------------


def setup_holder_asset(
    holder_kind: str = "LABEL",
    mfn_floor_cents: int = 100,
    work_kind: str = "FILM_CLIP",
    permitted_media: Optional[list] = None,
    embargo_until: Optional[str] = None,
    with_holder: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a holder (optional) and an asset linked to it. Returns (holder_or_None, asset)."""
    holder = None
    if with_holder:
        holder = create_rights_holder(holder_kind=holder_kind, mfn_floor_cents=mfn_floor_cents)
    asset = create_asset(
        work_kind=work_kind,
        permitted_media=permitted_media or ["STREAMING"],
        embargo_until=embargo_until,
        rights_holder_id=holder["id"] if holder else None,
    )
    return holder, asset


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — push a clearance request through the workflow
# ---------------------------------------------------------------------------


def setup_request_in_negotiating(
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-09-01T00:00:00Z",
    use_end_at: str = "2026-11-01T00:00:00Z",
    requested_units: int = 2,
    holder_kind: str = "LABEL",
    mfn_floor_cents: int = 100,
    work_kind: str = "FILM_CLIP",
    permitted_media: Optional[list] = None,
    requester_user_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Build holder + asset + request and advance to NEGOTIATING.

    Returns (holder, asset, request, requester_user_id).
    """
    holder, asset = setup_holder_asset(
        holder_kind=holder_kind,
        mfn_floor_cents=mfn_floor_cents,
        work_kind=work_kind,
        permitted_media=permitted_media or [media],
    )
    request, rid = create_clearance_request(
        asset["id"],
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        requester_user_id=requester_user_id,
    )
    req = advance_request(request["id"], request["version"])
    req = advance_request(request["id"], req["version"])
    return holder, asset, req, rid


def setup_approved_request(
    offered_fee_cents: int = 200000,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-09-01T00:00:00Z",
    use_end_at: str = "2026-11-01T00:00:00Z",
    requested_units: int = 2,
    holder_kind: str = "LABEL",
    mfn_floor_cents: int = 100,
    work_kind: str = "FILM_CLIP",
    permitted_media: Optional[list] = None,
    acceptor_role: str = "Negotiator",
    acceptor_user_id: Optional[str] = None,
    requester_user_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Build to NEGOTIATING then accept a round at offered_fee_cents.

    Returns (holder, asset, request, requester_user_id). Request is APPROVED.
    """
    holder, asset, req, rid = setup_request_in_negotiating(
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        holder_kind=holder_kind,
        mfn_floor_cents=mfn_floor_cents,
        work_kind=work_kind,
        permitted_media=permitted_media,
        requester_user_id=requester_user_id,
    )
    post_round(
        req["id"],
        offered_fee_cents,
        accept=True,
        role=acceptor_role,
        user_id=acceptor_user_id or _uid("neg"),
        holder_id=holder["id"] if acceptor_role == "RightsHolderRep" else None,
    )
    # Re-read the request to return its APPROVED view.
    officer = make_officer_headers(_uid("off"))
    resp = api_client.get_clearance_request(req["id"], officer)
    req_after = get_success_data(resp)
    return holder, asset, req_after, rid


def setup_license(
    fee_cents: int = 200000,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-09-01T00:00:00Z",
    use_end_at: str = "2026-11-01T00:00:00Z",
    requested_units: int = 5,
    holder_kind: str = "LABEL",
    mfn_floor_cents: int = 100,
    work_kind: str = "FILM_CLIP",
    permitted_media: Optional[list] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Full chain: holder + asset + request to NEGOTIATING + accepted round + grant.

    Returns (holder, asset, request, license, requester_user_id). License is ACTIVE/UNPAID.
    """
    holder, asset, req, rid = setup_approved_request(
        offered_fee_cents=fee_cents,
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        holder_kind=holder_kind,
        mfn_floor_cents=mfn_floor_cents,
        work_kind=work_kind,
        permitted_media=permitted_media,
    )
    lic = grant_license(req["id"], fee_cents)
    return holder, asset, req, lic, rid


# ---------------------------------------------------------------------------
# Tier 4: takedown / suspend / revoke shortcuts
# ---------------------------------------------------------------------------


def setup_license_with_pending_takedown(
    fee_cents: int = 200000,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-08-10T00:00:00Z",
    use_end_at: str = "2026-11-10T00:00:00Z",
    requested_units: int = 5,
    takedown_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """License granted, then a takedown filed (PENDING) at optional clock.

    If takedown_at is provided, the clock is advanced to that instant before filing.
    Returns (holder, asset, request, license, takedown_notice).
    """
    holder, asset, req, lic, _rid = setup_license(
        fee_cents=fee_cents,
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        permitted_media=[media],
    )
    if takedown_at is not None:
        api_client.set_clock(takedown_at, make_curator_headers(_uid("cur")))
    notice_headers = make_curator_headers(_uid("cur"))
    resp = api_client.file_takedown_notice(asset["id"], create_takedown_payload(), notice_headers)
    notice = get_success_data(resp)
    return holder, asset, req, lic, notice


def lapse_notice(notice_id: str, lapse_to: str) -> Dict[str, Any]:
    """Advance the clock so the notice's counter window lapses (PENDING→UPHELD sweep)."""
    api_client.set_clock(lapse_to, make_curator_headers(_uid("cur")))
    headers = make_curator_headers(_uid("cur"))
    resp = api_client.get_takedown_notice(notice_id, headers)
    return get_success_data(resp)


def setup_suspended_license(
    fee_cents: int = 200000,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-08-10T00:00:00Z",
    use_end_at: str = "2026-11-10T00:00:00Z",
    requested_units: int = 5,
    reservation_units: Optional[int] = None,
    takedown_at: Optional[str] = None,
    lapse_to: str = "2026-08-12T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """License granted (optionally with a HELD reservation), takedown filed,
    clock advanced to lapse the counter window. License ends SUSPENDED.

    Returns (holder, asset, request, license, notice, reservation_or_None).
    """
    holder, asset, req, lic, notice = setup_license_with_pending_takedown(
        fee_cents=fee_cents,
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        takedown_at=takedown_at,
    )
    reservation = None
    if reservation_units is not None:
        # Read fresh license version (the takedown filing may not bump license, but a clock
        # advance could sweep posture and license — read fresh to be safe).
        headers = make_payer_headers(_uid("fin"))
        lic_now = get_success_data(api_client.get_license(lic["id"], headers))
        ingest = make_ingest_headers(_uid("ing"))
        resp = api_client.create_reservation(
            lic["id"],
            {"units": reservation_units, "expected_license_version": lic_now["version"]},
            ingest,
        )
        reservation = get_success_data(resp)
    lapse_notice(notice["id"], lapse_to)
    return holder, asset, req, lic, notice, reservation


def setup_revoked_license(
    fee_cents: int = 200000,
    media: str = "STREAMING",
    territory: str = "NA",
    use_start_at: str = "2026-08-10T00:00:00Z",
    use_end_at: str = "2026-11-10T00:00:00Z",
    requested_units: int = 5,
    lapse_to: str = "2026-08-12T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """License granted, takedown filed, lapsed (UPHELD), then revoked by LegalCertifier.

    Returns (holder, asset, request, license, notice). License ends REVOKED.
    """
    holder, asset, req, lic, notice, _res = setup_suspended_license(
        fee_cents=fee_cents,
        media=media,
        territory=territory,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        lapse_to=lapse_to,
    )
    cert = make_certifier_headers(_uid("leg"))
    resp = api_client.revoke_license(lic["id"], cert)
    lic_after = get_success_data(resp)
    return holder, asset, req, lic_after, notice


# ---------------------------------------------------------------------------
# Tier 5: terminal-state shortcuts
# ---------------------------------------------------------------------------


def setup_expired_license(
    fee_cents: int = 200000,
    requested_units: int = 5,
    use_start_at: str = "2026-08-10T00:00:00Z",
    use_end_at: str = "2026-08-20T00:00:00Z",
    advance_clock_to: str = "2026-08-21T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """License granted with a short term, then clock advanced past term_end_at.

    Returns (holder, asset, request, license, requester_user_id). License is EXPIRED.
    """
    holder, asset, req, lic, rid = setup_license(
        fee_cents=fee_cents,
        use_start_at=use_start_at,
        use_end_at=use_end_at,
        requested_units=requested_units,
        permitted_media=["STREAMING"],
    )
    api_client.set_clock(advance_clock_to, make_curator_headers(_uid("cur")))
    headers = make_payer_headers(_uid("fin"))
    lic_now = get_success_data(api_client.get_license(lic["id"], headers))
    return holder, asset, req, lic_now, rid


def setup_orphan_certified_asset(
    log_channels: Tuple[str, str, str] = ("COPYRIGHT_OFFICE", "PERFORMING_RIGHTS_ORG", "UNION_GUILD"),
    day1: str = "2026-08-01T00:00:00Z",
    day2: str = "2026-08-16T00:00:00Z",
    day3: str = "2026-08-31T00:00:00Z",
) -> Dict[str, Any]:
    """Holder-less asset carried through the 3-log, >=30-day diligence rule.

    Default clock is 2026-08-01 so the first log posts without a clock call.
    Returns the asset (orphan_status should be ORPHAN_CERTIFIED).
    """
    asset = create_asset(work_kind="STILL_IMAGE", permitted_media=["PRINT"])
    curator = make_curator_headers(_uid("cur"))
    api_client.append_diligence_log(
        asset["id"],
        create_diligence_log_payload(search_channel=log_channels[0]),
        curator,
    )
    api_client.set_clock(day2, make_curator_headers(_uid("cur")))
    api_client.append_diligence_log(
        asset["id"],
        create_diligence_log_payload(search_channel=log_channels[1]),
        make_curator_headers(_uid("cur")),
    )
    api_client.set_clock(day3, make_curator_headers(_uid("cur")))
    api_client.append_diligence_log(
        asset["id"],
        create_diligence_log_payload(search_channel=log_channels[2]),
        make_curator_headers(_uid("cur")),
    )
    return asset
