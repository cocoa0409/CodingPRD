"""Composite setup builders.

The harness restarts the API against an empty database before every individual
test, so nothing here may assume pre-existing rows: each builder constructs the
state it needs from scratch through the endpoints PRD section 4 declares.

The builders are organised in five tiers:

* Tier 1 -- the logical clock.
* Tier 2 -- single entities in their initial state.
* Tier 3 -- entities driven to a particular point in their own state machine.
* Tier 4 -- multi-aggregate compositions (noticed meetings, officialized
  ordinances, locked cycles holding a conflict, eligible destruction batches).
* Tier 5 -- whole scenarios reused by more than one test.

Every builder returns the parsed ``data`` payload (or a dict of them) so callers
can read ids and versions without re-validating the envelope.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ANONYMOUS,
    CITY_CLERK,
    CODIFICATION_EDITOR,
    DEPUTY_CLERK,
    PRESIDING_OFFICER,
    RECORDS_OFFICER,
    make_requester_headers,
)
from .types import Entity, Headers

# ===========================================================================
# Tier 1 -- the logical clock (PRD 2.4)
# ===========================================================================


def set_clock(to_iso8601: str, headers: Headers = CITY_CLERK) -> Entity:
    """Move the server's logical clock to an arbitrary instant."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def reset_clock_to_default(headers: Headers = CITY_CLERK) -> Entity:
    """Return the clock to the default instant the PRD declares."""
    return set_clock(DEFAULT_CLOCK_UTC, headers)


# ===========================================================================
# Tier 2 -- single entities
# ===========================================================================


def create_venue(headers: Headers = CITY_CLERK, **overrides: Any) -> Entity:
    return get_success_data(
        api_client.create_venue(f.venue_payload(**overrides), headers), 201
    )


def create_meeting(
    venue_id: str, headers: Headers = CITY_CLERK, **overrides: Any
) -> Entity:
    return get_success_data(
        api_client.create_meeting(f.meeting_payload(venue_id, **overrides), headers), 201
    )


def create_number_series(headers: Headers = CITY_CLERK, **overrides: Any) -> Entity:
    return get_success_data(
        api_client.create_number_series(f.number_series_payload(**overrides), headers),
        201,
    )


def create_code_title(
    headers: Headers = CODIFICATION_EDITOR, **overrides: Any
) -> Entity:
    return get_success_data(
        api_client.create_code_title(f.code_title_payload(**overrides), headers), 201
    )


def create_supplement_cycle(
    title_id: str, headers: Headers = CODIFICATION_EDITOR, **overrides: Any
) -> Entity:
    return get_success_data(
        api_client.create_supplement_cycle(
            title_id, f.supplement_cycle_payload(**overrides), headers
        ),
        201,
    )


def create_record_series(headers: Headers = RECORDS_OFFICER, **overrides: Any) -> Entity:
    return get_success_data(
        api_client.create_record_series(f.record_series_payload(**overrides), headers),
        201,
    )


def create_records_request(headers: Headers = ANONYMOUS, **overrides: Any) -> Entity:
    return get_success_data(
        api_client.create_records_request(f.records_request_payload(**overrides), headers),
        201,
    )


def create_ordinance(
    number_series_id: str, headers: Headers = CITY_CLERK, **overrides: Any
) -> Entity:
    return get_success_data(
        api_client.create_instrument(
            f.ordinance_payload(number_series_id, **overrides), headers
        ),
        201,
    )


def create_resolution(
    number_series_id: str, headers: Headers = CITY_CLERK, **overrides: Any
) -> Entity:
    return get_success_data(
        api_client.create_instrument(
            f.resolution_payload(number_series_id, **overrides), headers
        ),
        201,
    )


def create_code_amendment(
    number_series_id: str,
    code_title_id: str,
    code_section_ref: str = "12.04.030",
    headers: Headers = CITY_CLERK,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api_client.create_instrument(
            f.code_amendment_payload(
                number_series_id, code_title_id, code_section_ref, **overrides
            ),
            headers,
        ),
        201,
    )


# --- small readers ---------------------------------------------------------


def read_meeting(meeting_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_meeting(meeting_id, headers))


def meeting_version(meeting_id: str, headers: Headers = CITY_CLERK) -> int:
    return read_meeting(meeting_id, headers)["version"]


def read_packet(packet_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_agenda_packet(packet_id, headers))


def read_code_title(title_id: str, headers: Headers = CODIFICATION_EDITOR) -> Entity:
    return get_success_data(api_client.get_code_title(title_id, headers))


def code_title_version(title_id: str, headers: Headers = CODIFICATION_EDITOR) -> int:
    return read_code_title(title_id, headers)["version"]


def read_cycle(cycle_id: str, headers: Headers = CODIFICATION_EDITOR) -> Entity:
    return get_success_data(api_client.get_supplement_cycle(cycle_id, headers))


def read_submission(
    submission_id: str, headers: Headers = CODIFICATION_EDITOR
) -> Entity:
    return get_success_data(
        api_client.get_codification_submission(submission_id, headers)
    )


def read_instrument(instrument_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_instrument(instrument_id, headers))


def read_notice(notice_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_publication_notice(notice_id, headers))


def read_motion(motion_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_motion(motion_id, headers))


def read_minutes(minutes_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_minutes(minutes_id, headers))


def read_records_request(request_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.get_records_request(request_id, headers))


def read_record_series(series_id: str, headers: Headers = RECORDS_OFFICER) -> Entity:
    return get_success_data(api_client.get_record_series(series_id, headers))


def read_batch(batch_id: str, headers: Headers = RECORDS_OFFICER) -> Entity:
    return get_success_data(api_client.get_destruction_batch(batch_id, headers))


def list_notices_for_meeting(
    meeting_id: str, headers: Headers = CITY_CLERK
) -> List[Entity]:
    body = api_client.list_publication_notices(headers, {"meeting_id": meeting_id})
    return get_success_data(body)


def list_notices_for_instrument(
    instrument_id: str, headers: Headers = CITY_CLERK
) -> List[Entity]:
    body = api_client.list_publication_notices(headers, {"instrument_id": instrument_id})
    return get_success_data(body)


def sole_notice_for_meeting(meeting_id: str, headers: Headers = CITY_CLERK) -> Entity:
    notices = list_notices_for_meeting(meeting_id, headers)
    assert notices, f"expected a publication notice for meeting {meeting_id}"
    return notices[0]


def sole_notice_for_instrument(
    instrument_id: str, headers: Headers = CITY_CLERK
) -> Entity:
    notices = list_notices_for_instrument(instrument_id, headers)
    assert notices, f"expected a publication notice for instrument {instrument_id}"
    return notices[0]


def sole_minutes_of_meeting(meeting_id: str, headers: Headers = CITY_CLERK) -> Entity:
    rows = get_success_data(api_client.list_meeting_minutes(meeting_id, headers))
    assert rows, f"expected a minutes record for meeting {meeting_id}"
    return rows[0]


# ===========================================================================
# Tier 3 -- entities driven along their own state machine
# ===========================================================================


def scheduled_meeting(
    venue_overrides: Optional[Dict[str, Any]] = None, **meeting_overrides: Any
) -> Dict[str, Entity]:
    """A venue plus a meeting in its initial SCHEDULED state."""
    venue = create_venue(**(venue_overrides or {}))
    meeting = create_meeting(venue["id"], **meeting_overrides)
    return {"venue": venue, "meeting": meeting}


def draft_packet(
    meeting_id: str, headers: Headers = CITY_CLERK, **overrides: Any
) -> Entity:
    """The next agenda packet revision, filed against the meeting's current
    version so the concurrency guard of PRD 2.7 is satisfied."""
    expected = overrides.pop(
        "expected_meeting_version", meeting_version(meeting_id, headers)
    )
    return get_success_data(
        api_client.create_agenda_packet(
            meeting_id, f.agenda_packet_payload(expected, **overrides), headers
        ),
        201,
    )


def add_item(
    packet_id: str,
    sequence_number: int = 1,
    item_type: str = "REPORT",
    headers: Headers = CITY_CLERK,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api_client.create_agenda_item(
            packet_id,
            f.agenda_item_payload(sequence_number, item_type, **overrides),
            headers,
        ),
        201,
    )


def post_packet(packet_id: str, headers: Headers = CITY_CLERK) -> Entity:
    return get_success_data(api_client.post_agenda_packet(packet_id, headers))


def noticed_meeting(
    item_types: Optional[List[str]] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    packet_overrides: Optional[Dict[str, Any]] = None,
    **meeting_overrides: Any,
) -> Dict[str, Any]:
    """A meeting driven to NOTICED behind a posted packet.

    Returns the venue, the meeting as it reads after posting, the packet and the
    DRAFT ``MEETING_AGENDA`` notice that posting creates (PRD 3.2).
    """
    base = scheduled_meeting(venue_overrides, **meeting_overrides)
    packet = draft_packet(base["meeting"]["id"], **(packet_overrides or {}))
    for index, item_type in enumerate(item_types or ["REPORT"], start=1):
        add_item(packet["id"], index, item_type)
    posted = post_packet(packet["id"])
    return {
        "venue": base["venue"],
        "meeting": read_meeting(base["meeting"]["id"]),
        "packet": posted,
        "agenda_notice": sole_notice_for_meeting(base["meeting"]["id"]),
    }


def in_session_meeting(
    present_member_count: int = 5,
    item_types: Optional[List[str]] = None,
    **meeting_overrides: Any,
) -> Dict[str, Any]:
    """A NOTICED meeting called to order by the presiding officer (PRD 3.3)."""
    ctx = noticed_meeting(item_types=item_types, **meeting_overrides)
    convened = get_success_data(
        api_client.convene_meeting(
            ctx["meeting"]["id"],
            f.convene_payload(present_member_count),
            PRESIDING_OFFICER,
        )
    )
    ctx["meeting"] = convened
    return ctx


def record_motion(
    meeting_id: str,
    motion_type: str = "PROCEDURAL",
    majority_rule: str = "SIMPLE",
    headers: Headers = CITY_CLERK,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api_client.create_motion(
            f.motion_payload(meeting_id, motion_type, majority_rule, **overrides),
            headers,
        ),
        201,
    )


def tally(
    motion_id: str,
    yes_count: int,
    no_count: int,
    abstain_count: int = 0,
    recused_count: int = 0,
    headers: Headers = CITY_CLERK,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api_client.tally_motion(
            motion_id,
            f.tally_payload(
                yes_count, no_count, abstain_count, recused_count, **overrides
            ),
            headers,
        )
    )


def adjourn(meeting_id: str) -> Entity:
    return get_success_data(api_client.adjourn_meeting(meeting_id, PRESIDING_OFFICER))


def adjourned_meeting_with_minutes(
    present_member_count: int = 5,
    item_types: Optional[List[str]] = None,
    **meeting_overrides: Any,
) -> Dict[str, Any]:
    """A meeting adjourned so that its DRAFT minutes exist (PRD 3.4)."""
    ctx = in_session_meeting(present_member_count, item_types, **meeting_overrides)
    ctx["meeting"] = adjourn(ctx["meeting"]["id"])
    ctx["minutes"] = sole_minutes_of_meeting(ctx["meeting"]["id"])
    return ctx


def submitted_minutes(
    minutes_id: str,
    text_body: str = "The finance report was received and filed.",
    author: Headers = DEPUTY_CLERK,
) -> Entity:
    """Write the narrative and submit it for approval at a later meeting."""
    get_success_data(
        api_client.update_minutes(minutes_id, f.minutes_narrative_payload(text_body), author)
    )
    return get_success_data(api_client.submit_minutes(minutes_id, CITY_CLERK))


# ===========================================================================
# Tier 4 -- multi-aggregate compositions
# ===========================================================================


def introduced_ordinance_at_first_reading(
    meeting_id: str,
    number_series_id: str,
    **instrument_overrides: Any,
) -> Entity:
    """An ordinance introduced and advanced through its first reading at a
    meeting that is in session (PRD 3.5)."""
    instrument = create_ordinance(number_series_id, **instrument_overrides)
    return get_success_data(
        api_client.advance_reading(
            instrument["id"], f.advance_reading_payload(meeting_id), CITY_CLERK
        )
    )


def adopted_unofficial_ordinance(
    present_member_count: int = 7,
    number_series_overrides: Optional[Dict[str, Any]] = None,
    instrument_overrides: Optional[Dict[str, Any]] = None,
    clock_at_vote: Optional[str] = "2026-09-15T18:00:00Z",
    **meeting_overrides: Any,
) -> Dict[str, Any]:
    """One ordinance carried by a passing ORDINANCE_ADOPTION motion, with the
    recording meeting adjourned and its minutes submitted.

    At this point the instrument sits in ADOPTED_UNOFFICIAL, unnumbered, and the
    minutes wait for approval at a later meeting (PRD 3.3, 3.4).

    The clock is advanced to the sitting's own day before the motion is recorded,
    because PRD 3.3 stamps ``voted_on`` from "the logical clock date" at the tally
    and the vote is cast at the meeting, not on the day the calendar was written.
    """
    series = create_number_series(**(number_series_overrides or {}))
    ctx = in_session_meeting(
        present_member_count,
        item_types=["ORDINANCE_ADOPTION"],
        **meeting_overrides,
    )
    meeting_id = ctx["meeting"]["id"]
    if clock_at_vote is not None:
        set_clock(clock_at_vote)
    instrument = introduced_ordinance_at_first_reading(
        meeting_id, series["id"], **(instrument_overrides or {})
    )
    motion = record_motion(
        meeting_id, "ORDINANCE_ADOPTION", "SIMPLE", instrument_id=instrument["id"]
    )
    tallied = tally(motion["id"], present_member_count - 2, 2)
    ctx["meeting"] = adjourn(meeting_id)
    minutes = sole_minutes_of_meeting(meeting_id)
    submitted = submitted_minutes(
        minutes["id"], "The ordinance was adopted at this meeting."
    )
    return {
        **ctx,
        "number_series": series,
        "instrument": read_instrument(instrument["id"]),
        "motion": tallied,
        "minutes": submitted,
    }


def approve_minutes_at_later_meeting(
    minutes_id: str,
    present_member_count: int = 7,
    venue_id: Optional[str] = None,
    clock_at: Optional[str] = "2026-10-06T18:00:00Z",
    scheduled_start: str = "2026-10-06T18:00:00Z",
    scheduled_end: str = "2026-10-06T21:00:00Z",
    yes_count: Optional[int] = None,
    no_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Approve submitted minutes by carrying a MINUTES_APPROVAL motion at a
    later meeting, which is the only pathway PRD 3.4 declares."""
    if venue_id is None:
        venue_id = create_venue(name="Annex Hearing Room", address="9 Civic Plaza")["id"]
    meeting = create_meeting(
        venue_id, scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    packet = draft_packet(meeting["id"])
    add_item(packet["id"], 1, "MINUTES", title="Approval of the prior minutes")
    post_packet(packet["id"])
    if clock_at is not None:
        set_clock(clock_at)
    get_success_data(
        api_client.convene_meeting(
            meeting["id"], f.convene_payload(present_member_count), PRESIDING_OFFICER
        )
    )
    motion = record_motion(
        meeting["id"], "MINUTES_APPROVAL", "SIMPLE", target_minutes_id=minutes_id
    )
    if yes_count is None:
        yes_count = present_member_count - 2
    if no_count is None:
        no_count = present_member_count - yes_count
    tallied = tally(motion["id"], yes_count, no_count)
    return {"meeting": meeting, "packet": packet, "motion": tallied}


def officialized_ordinance(
    present_member_count: int = 7,
    number_series_overrides: Optional[Dict[str, Any]] = None,
    instrument_overrides: Optional[Dict[str, Any]] = None,
    clock_at_approval: Optional[str] = "2026-10-06T18:00:00Z",
) -> Dict[str, Any]:
    """The full four-hop officialization of PRD 3.4: an adopted ordinance whose
    minutes have been approved, so the number is minted and the publication
    notice exists in DRAFT."""
    base = adopted_unofficial_ordinance(
        present_member_count,
        number_series_overrides,
        instrument_overrides,
    )
    approval = approve_minutes_at_later_meeting(
        base["minutes"]["id"],
        present_member_count,
        venue_id=None,
        clock_at=clock_at_approval,
    )
    instrument = read_instrument(base["instrument"]["id"])
    return {
        **base,
        "approval_meeting": approval["meeting"],
        "approval_motion": approval["motion"],
        "instrument": instrument,
        "minutes": read_minutes(base["minutes"]["id"]),
        "number_series": get_success_data(
            api_client.get_number_series(base["number_series"]["id"], CITY_CLERK)
        ),
        "notice": sole_notice_for_instrument(instrument["id"]),
    }


def ordered_notice(
    notice_id: str,
    publication_dates: List[str],
    column_inches: float = 20.0,
    affidavit_required: bool = False,
    headers: Headers = CITY_CLERK,
) -> Entity:
    """Place the insertion order, which prices the invoice (PRD 3.6)."""
    return get_success_data(
        api_client.order_publication(
            notice_id,
            f.publication_order_payload(
                publication_dates, column_inches, affidavit_required
            ),
            headers,
        )
    )


def certify_notice(
    notice_id: str, publication_completed_on: str, headers: Headers = CITY_CLERK
) -> Entity:
    return get_success_data(
        api_client.certify_publication(
            notice_id, f.certify_publication_payload(publication_completed_on), headers
        )
    )


def code_title_with_open_cycle(
    title_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides: Any,
) -> Dict[str, Entity]:
    """A code title carrying one OPEN supplement cycle (PRD 3.7)."""
    title = create_code_title(**(title_overrides or {}))
    cycle = create_supplement_cycle(title["id"], **cycle_overrides)
    return {"code_title": title, "cycle": cycle}


def file_submission(
    cycle_id: str,
    instrument_id: str,
    code_title_id: str,
    code_section_ref: str = "12.04.030",
    action: str = "ADD",
    headers: Headers = CODIFICATION_EDITOR,
) -> Entity:
    """File a client-origin submission using the code title's current version."""
    return get_success_data(
        api_client.create_codification_submission(
            f.codification_submission_payload(
                cycle_id,
                instrument_id,
                code_title_version(code_title_id),
                code_section_ref,
                action,
            ),
            headers,
        ),
        201,
    )


def locked_cycle_with_conflict(
    section_ref: str = "12.04.030",
    first_category: str = "CODE_AMENDMENT",
    second_category: str = "CODE_AMENDMENT",
    filer: Headers = CODIFICATION_EDITOR,
    action: str = "ADD",
    **cycle_overrides: Any,
) -> Dict[str, Any]:
    """Two submissions colliding on one code section, held as a conflict pair
    inside a LOCKED cycle (PRD 3.7)."""
    series = create_number_series()
    pair = code_title_with_open_cycle(**cycle_overrides)
    title_id = pair["code_title"]["id"]
    first = create_code_amendment(
        series["id"],
        title_id,
        section_ref,
        ordinance_category=first_category,
        title=f"Amending {section_ref} (parking)",
        full_text_length=1500,
    )
    second = create_code_amendment(
        series["id"],
        title_id,
        section_ref,
        ordinance_category=second_category,
        title=f"Amending {section_ref} (setbacks)",
        full_text_length=1500,
    )
    sub_one = file_submission(
        pair["cycle"]["id"], first["id"], title_id, section_ref, action, filer
    )
    sub_two = file_submission(
        pair["cycle"]["id"], second["id"], title_id, section_ref, action, filer
    )
    locked = get_success_data(
        api_client.lock_supplement_cycle(pair["cycle"]["id"], filer)
    )
    return {
        "number_series": series,
        "code_title": read_code_title(title_id),
        "cycle": locked,
        "instrument_one": first,
        "instrument_two": second,
        "submission_one": read_submission(sub_one["id"]),
        "submission_two": read_submission(sub_two["id"]),
    }


def series_eligible_for_destruction(
    item_count: int = 40,
    accessioned_on: str = "2019-06-15",
    retention_years: int = 5,
    **series_overrides: Any,
) -> Entity:
    """A record series whose retention period has already elapsed against the
    default clock, so a destruction batch may be proposed (PRD 3.9)."""
    series = create_record_series(
        retention_years=retention_years, **series_overrides
    )
    get_success_data(
        api_client.create_accession(
            series["id"], f.accession_payload(item_count, accessioned_on), RECORDS_OFFICER
        )
    )
    return read_record_series(series["id"])


def proposed_destruction_batch(
    series_id: str,
    item_count: int = 10,
    cutoff_on: str = "2019-06-15",
    headers: Headers = RECORDS_OFFICER,
) -> Entity:
    return get_success_data(
        api_client.create_destruction_batch(
            f.destruction_batch_payload(series_id, item_count, cutoff_on), headers
        ),
        201,
    )


def certified_destruction_batch(
    series_id: str,
    item_count: int = 10,
    cutoff_on: str = "2019-06-15",
    proposer: Headers = RECORDS_OFFICER,
    certifier: Headers = CITY_CLERK,
    certified_on: str = "2026-08-01",
) -> Entity:
    """A batch signed by an officer other than its proposer (PRD 2.8)."""
    batch = proposed_destruction_batch(series_id, item_count, cutoff_on, proposer)
    return get_success_data(
        api_client.certify_destruction_batch(
            batch["id"], f.certify_batch_payload(certified_on), certifier
        )
    )


# ===========================================================================
# Tier 5 -- whole scenarios
# ===========================================================================


def request_under_review(
    reviewer: Headers = CITY_CLERK, **request_overrides: Any
) -> Entity:
    """A records request whose disclosure axis has been opened (PRD 3.8)."""
    request = create_records_request(**request_overrides)
    return get_success_data(api_client.begin_review(request["id"], reviewer))


def request_in_exemption_review(
    exemption_claims: Optional[List[str]] = None, **request_overrides: Any
) -> Entity:
    request = request_under_review(**request_overrides)
    return get_success_data(
        api_client.exemption_review(
            request["id"], f.exemption_review_payload(exemption_claims), RECORDS_OFFICER
        )
    )


def assessed_request(
    fee_lines: List[Dict[str, Any]],
    fee_schedule_variant: str = "ACTUAL_COST",
    assessor: Headers = CITY_CLERK,
    **request_overrides: Any,
) -> Entity:
    """A records request under review with a fee assessed against it."""
    request = request_under_review(**request_overrides)
    return get_success_data(
        api_client.assess_fee(
            request["id"],
            f.assess_fee_payload(fee_lines, fee_schedule_variant),
            assessor,
        )
    )


def pay_request(request_id: str, amount_cents: int) -> Entity:
    """Pay from the requester's own credential, which PRD 2.1 defines as the
    request id itself."""
    return get_success_data(
        api_client.record_payment(
            request_id,
            f.payment_payload(amount_cents),
            make_requester_headers(request_id),
        )
    )


def released_request(
    fee_lines: Optional[List[Dict[str, Any]]] = None,
    **request_overrides: Any,
) -> Entity:
    """A request disposed by FULL_RELEASE, optionally carrying an assessed fee."""
    if fee_lines is None:
        request = request_under_review(**request_overrides)
    else:
        request = assessed_request(fee_lines, **request_overrides)
    return get_success_data(
        api_client.record_disposition(
            request["id"], f.disposition_payload("FULL_RELEASE"), CITY_CLERK
        )
    )


def closed_request(
    target_series_id: Optional[str] = None, **request_overrides: Any
) -> Entity:
    """A request driven all the way to CLOSED, which is what the
    REQUEST_CLOSURE retention anchor reads (PRD 3.9)."""
    overrides = dict(request_overrides)
    if target_series_id is not None:
        overrides["target_series_id"] = target_series_id
    request = released_request(**overrides)
    return get_success_data(api_client.close_records_request(request["id"], CITY_CLERK))


def approved_minutes_ready_for_correction(
    present_member_count: int = 6,
) -> Dict[str, Any]:
    """Minutes of one meeting approved at a later meeting, which is the only
    state from which a correction may be opened (PRD 3.4)."""
    ctx = adjourned_meeting_with_minutes(present_member_count)
    created = ctx["minutes"]
    submitted_minutes(created["id"])
    approval = approve_minutes_at_later_meeting(created["id"], present_member_count)
    return {
        **ctx,
        "minutes_at_creation": created,
        "minutes": read_minutes(created["id"]),
        "approval_meeting": approval["meeting"],
        "approval_motion": approval["motion"],
    }


def open_correction(
    minutes_id: str,
    corrected_text_body: str = "The finance report was received, filed and referred to committee.",
    headers: Headers = DEPUTY_CLERK,
) -> Entity:
    """Park a corrected narrative against APPROVED minutes (PRD 3.4)."""
    version = read_minutes(minutes_id)["version"]
    return get_success_data(
        api_client.open_minutes_correction(
            minutes_id,
            f.minutes_correction_payload(version, corrected_text_body),
            headers,
        )
    )


def ordinance_and_resolution_adopted_together() -> Dict[str, Any]:
    """One ordinance and one resolution introduced and adopted at the same
    council meeting, with the minutes of that meeting approved on 2026-10-06.

    Both instruments therefore share an ``adoption_date`` and both draw their
    numbers in the same officialization cascade, which is what isolates the
    effective-date basis as the only difference between them (PRD 3.4, 3.5).
    """
    venue = create_venue()
    ord_series = create_number_series(instrument_class="ORDINANCE")
    res_series = create_number_series(instrument_class="RESOLUTION")
    ordinance = create_ordinance(
        ord_series["id"],
        ordinance_category="GENERAL",
        title="An ordinance amending parking hours",
        full_text_length=1200,
    )
    resolution = create_resolution(
        res_series["id"],
        title="A resolution honouring the fire brigade",
        full_text_length=800,
    )
    september = create_meeting(venue["id"])
    packet = draft_packet(september["id"])
    add_item(packet["id"], 1, "ORDINANCE_FIRST_READING", title="First reading")
    add_item(packet["id"], 2, "ORDINANCE_ADOPTION", title="Adoption")
    add_item(packet["id"], 3, "RESOLUTION", title="Resolution")
    set_clock("2026-09-12T18:00:00Z")
    post_packet(packet["id"])
    set_clock("2026-09-15T18:00:00Z")
    get_success_data(
        api_client.convene_meeting(
            september["id"], f.convene_payload(7), PRESIDING_OFFICER
        )
    )
    get_success_data(
        api_client.advance_reading(
            ordinance["id"], f.advance_reading_payload(september["id"]), CITY_CLERK
        )
    )
    ord_motion = record_motion(
        september["id"], "ORDINANCE_ADOPTION", "SIMPLE", instrument_id=ordinance["id"]
    )
    tally(ord_motion["id"], 4, 3)
    res_motion = record_motion(
        september["id"], "RESOLUTION_ADOPTION", "SIMPLE", instrument_id=resolution["id"]
    )
    tally(res_motion["id"], 5, 2)
    adjourn(september["id"])
    minutes = sole_minutes_of_meeting(september["id"])
    submitted_minutes(
        minutes["id"], "Minutes of the regular council meeting of 15 September 2026."
    )

    october = create_meeting(
        venue["id"],
        scheduled_start="2026-10-06T18:00:00Z",
        scheduled_end="2026-10-06T21:00:00Z",
    )
    packet_oct = draft_packet(october["id"])
    add_item(packet_oct["id"], 1, "MINUTES", title="Approval of the September minutes")
    set_clock("2026-10-03T18:00:00Z")
    post_packet(packet_oct["id"])
    set_clock("2026-10-06T18:00:00Z")
    get_success_data(
        api_client.convene_meeting(october["id"], f.convene_payload(7), PRESIDING_OFFICER)
    )
    approval_motion = record_motion(
        october["id"], "MINUTES_APPROVAL", "SIMPLE", target_minutes_id=minutes["id"]
    )
    tally(approval_motion["id"], 5, 2)

    return {
        "venue": venue,
        "ordinance_series": ord_series,
        "resolution_series": res_series,
        "ordinance": read_instrument(ordinance["id"]),
        "resolution": read_instrument(resolution["id"]),
        "september_meeting": september,
        "october_meeting": october,
        "minutes": read_minutes(minutes["id"]),
        "ordinance_notice": sole_notice_for_instrument(ordinance["id"]),
    }


def additional_meeting_in_session(
    scheduled_start: str,
    scheduled_end: str,
    post_at: str,
    convene_at: str,
    present_member_count: int = 7,
    item_types: Optional[List[str]] = None,
    venue_name: str = "Overflow Room",
    venue_address: str = "7 Civic Plaza",
    venue_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A further meeting noticed and called to order in its own room, for the
    later sittings at which minutes and vetoes are taken up (PRD 3.3, 3.4)."""
    if venue_id is None:
        venue_id = create_venue(name=venue_name, address=venue_address)["id"]
    meeting = create_meeting(
        venue_id, scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    packet = draft_packet(meeting["id"])
    for index, item_type in enumerate(item_types or ["REPORT"], start=1):
        add_item(packet["id"], index, item_type)
    set_clock(post_at)
    post_packet(packet["id"])
    set_clock(convene_at)
    convened = get_success_data(
        api_client.convene_meeting(
            meeting["id"], f.convene_payload(present_member_count), PRESIDING_OFFICER
        )
    )
    return {"venue_id": venue_id, "meeting": convened, "packet": packet}


def vetoed_ordinance(
    veto_reason: str = "The overnight parking restriction exceeds the enabling authority.",
    **kwargs: Any,
) -> Dict[str, Any]:
    """An officialized ordinance vetoed by the presiding officer, which voids the
    publication notice adoption had created (PRD 3.5)."""
    scenario = officialized_ordinance(**kwargs)
    vetoed = get_success_data(
        api_client.veto_instrument(
            scenario["instrument"]["id"], f.veto_payload(veto_reason=veto_reason), PRESIDING_OFFICER
        )
    )
    return {
        **scenario,
        "instrument": vetoed,
        "first_notice": read_notice(scenario["notice"]["id"]),
    }


def code_amendment_ordered_for_publication(
    section_ref: str = "12.04.030",
) -> Dict[str, Any]:
    """A CODE_AMENDMENT ordinance carried all the way to an ORDERED newspaper
    notice, with a competing ordinance's client submission already sitting on the
    same code section inside the cycle the cascade will select (PRD 3.6, 3.7).

    Certifying the returned notice is the single call that runs the
    publication-to-codification cascade.
    """
    pair = code_title_with_open_cycle(
        window_open_on="2026-10-01", window_close_on="2026-10-31"
    )
    title_id = pair["code_title"]["id"]
    scenario = officialized_ordinance(
        7,
        instrument_overrides={
            "ordinance_category": "CODE_AMENDMENT",
            "code_title_id": title_id,
            "code_section_ref": section_ref,
            "full_text_length": 1200,
            "title": f"An ordinance amending section {section_ref}",
        },
    )
    competing = create_code_amendment(
        scenario["number_series"]["id"],
        title_id,
        section_ref,
        full_text_length=1500,
        title=f"A competing ordinance rewriting section {section_ref}",
    )
    client_submission = file_submission(
        pair["cycle"]["id"], competing["id"], title_id, section_ref, "ADD"
    )
    notice = ordered_notice(
        scenario["notice"]["id"],
        ["2026-10-07", "2026-10-14"],
        column_inches=12.50,
        affidavit_required=True,
    )
    set_clock("2026-10-14T09:00:00Z")
    return {
        **scenario,
        **pair,
        "notice": notice,
        "competing_instrument": competing,
        "client_submission": client_submission,
    }


def submissions_for_instrument(
    instrument_id: str, headers: Headers = CODIFICATION_EDITOR
) -> List[Entity]:
    return get_success_data(
        api_client.list_codification_submissions(headers, {"instrument_id": instrument_id})
    )


def place_legal_hold(
    series_id: str,
    legal_hold_status: str = "LITIGATION_HOLD",
    headers: Headers = RECORDS_OFFICER,
) -> Entity:
    """Place or lift a hold on a record series, which recomputes its eligibility
    date and advances its version (PRD 3.9)."""
    return get_success_data(
        api_client.update_record_series(
            series_id,
            f.record_series_update_payload(legal_hold_status=legal_hold_status),
            headers,
        )
    )
