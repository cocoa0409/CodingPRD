"""Role-based access control, segregation of duties, optimistic concurrency on a
parent row's version, and the synchronous visibility of cascade side effects."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    FINANCE_HEADERS,
    FINANCE_HEADERS_2,
    FINANCE_USER_ID,
    FINANCE_USER_ID_2,
    REGISTRAR_HEADERS,
    REGISTRAR_HEADERS_2,
    REGISTRAR_USER_ID_2,
    guardian_headers,
    panelist_headers,
)

# Calendar instants used by the event-based scenarios below. All of them sit
# after the fixture clock (2026-08-05T09:00:00Z) and inside the season year.
CONCERT_START = "2026-11-15T19:00:00Z"
CONCERT_END = "2026-11-15T21:00:00Z"
ELIGIBILITY_WINDOW_START = "2026-10-01T00:00:00Z"
REHEARSAL_START = "2026-10-05T18:00:00Z"
REHEARSAL_END = "2026-10-05T20:00:00Z"


# ---------------------------------------------------------------------------
# Local builders (the shared helpers cover everything up to an accepted offer;
# these add the calendar rows and the multi-seat sections used further down).
# ---------------------------------------------------------------------------

def _seated_member_on_concert(api: ApiClient) -> Dict[str, Any]:
    """An accepted offer plus a concert roster row for the seated musician."""
    ctx = X.accepted_placement(api)
    ctx["event"] = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="CONCERT",
        start_at=CONCERT_START,
        end_at=CONCERT_END,
        eligibility_window_start=ELIGIBILITY_WINDOW_START,
    )
    ctx["participation"] = X.create_participation(
        api, ctx["event"]["id"], ctx["member"]["id"]
    )
    return ctx


def _placement_ready_season(
    api: ApiClient,
    member_count: int = 2,
    quota_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A season in `PLACEMENT` holding `member_count` adjudicated auditions."""
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    ensemble = X.create_ensemble(api, season["id"], min_total_size=1, max_total_size=6)
    quota = X.create_section_quota(api, ensemble["id"], **(quota_overrides or {}))
    panelists = X.create_panelists(api, count=3)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api, season["id"], [p["id"] for p in panelists], capacity=8
    )

    members = []
    auditions = []
    for index in range(member_count):
        member = X.create_member(api, legal_name=f"Concurrent Player {index + 1}")
        audition = X.create_audition(api, member["id"], season["id"])
        X.schedule_audition(api, audition["id"], slot["id"])
        X.submit_uniform_sheets(api, audition["id"], panelists, 20)
        members.append(member)
        auditions.append(X.adjudicate(api, audition["id"]))

    season = X.advance_season(api, season["id"], "PLACEMENT")
    return {
        "season": season,
        "ensemble": ensemble,
        "quota": quota,
        "members": members,
        "auditions": auditions,
    }


def _offer_and_accept(api: ApiClient, ctx: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Offer the indexed audition a chair and have its Guardian accept it."""
    placement = X.create_placement(
        api, ctx["auditions"][index]["id"], ctx["ensemble"]["id"], offer_kind="OFFER"
    )
    return X.accept_placement(api, placement["id"], ctx["members"][index]["id"])


def _reviewed_aid_request(api: ApiClient, amount_cents: int = 40000) -> Dict[str, Any]:
    """An accepted offer whose account sits in `UNDER_REVIEW` for `FINANCE_USER_ID`."""
    ctx = X.accepted_placement(api)
    account_id = ctx["account"]["id"]
    validate_success(
        api.request_aid(
            account_id,
            F.aid_request_payload(amount_cents),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    account = validate_success(api.review_aid(account_id, {}, FINANCE_HEADERS))
    assert account["aid_status"] == "UNDER_REVIEW"
    assert account["aid_reviewed_by_user_id"] == FINANCE_USER_ID
    ctx["account"] = account
    return ctx


# ---------------------------------------------------------------------------
# Every role drives its own exclusive part of one musician's journey
# ---------------------------------------------------------------------------

def test_all_five_roles_drive_one_musician_from_quorum_to_eligibility_review(api):
    """One musician's whole journey succeeds when each write is issued by the single role that owns it.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/each_role_executes_its_own_exclusive_operations_end_to_end
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api, name="2026-2027 Season", year_label="2026-27")
    ensemble = X.create_ensemble(api, season["id"], name="Philharmonic")
    X.create_section_quota(api, ensemble["id"])
    member = X.create_member(api, legal_name="Ada Strings")
    panelists = X.create_panelists(api, count=3)
    X.advance_season(api, season["id"], "AUDITIONS_OPEN")
    slot = X.create_audition_slot(
        api, season["id"], [p["id"] for p in panelists], capacity=4
    )
    audition = X.create_audition(api, member["id"], season["id"])
    X.schedule_audition(api, audition["id"], slot["id"])
    X.submit_uniform_sheets(api, audition["id"], panelists[:2], 20)

    # Panelist: the third blind sheet closes the quorum.
    sheet = validate_success(
        api.submit_panel_score(
            audition["id"],
            F.uniform_panel_score_payload(panelists[2]["id"], 20),
            panelist_headers(panelists[2]["id"]),
        ),
        201,
    )
    assert sheet["panelist_id"] == panelists[2]["id"]
    assert X.read_audition(api, audition["id"])["status"] == "SCORED"

    # ArtisticDirector: adjudicate, advance the phase, create the offer.
    adjudicated = validate_success(
        api.adjudicate_audition(audition["id"], {}, DIRECTOR_HEADERS)
    )
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["composite_final_score"] == 80.00
    assert adjudicated["tier_recommendation"] == "PHILHARMONIC"

    placement_phase = validate_success(
        api.advance_season_status(
            season["id"], F.advance_status_payload("PLACEMENT"), DIRECTOR_HEADERS
        )
    )
    assert placement_phase["status"] == "PLACEMENT"

    placement = validate_success(
        api.create_placement(
            F.placement_payload(
                audition["id"], ensemble["id"], X.ensemble_version(api, ensemble["id"])
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert placement["status"] == "OFFERED"

    # Guardian: accept the offer and pay against the account it opened.
    accepted = validate_success(
        api.accept_placement(
            placement["id"],
            F.accept_payload(instrument_loan_requested=False),
            guardian_headers(member["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"

    account = X.sole_account(api, member["id"], season["id"])
    paid = validate_success(
        api.record_payment(
            account["id"], F.payment_payload(23223), guardian_headers(member["id"])
        ),
        201,
    )
    assert paid["payments_total_cents"] == 23223
    assert paid["balance_cents"] == 100000

    # FinanceOfficer: finalize the assessment and open the aid review.
    finalized = validate_success(
        api.finalize_assessment(account["id"], {}, FINANCE_HEADERS)
    )
    assert finalized["assessment_variant"] == "FINAL"
    assert finalized["assessed_cents"] == 123223
    assert finalized["balance_cents"] == 100000

    requested = validate_success(
        api.request_aid(
            account["id"],
            F.aid_request_payload(10000),
            guardian_headers(member["id"]),
        )
    )
    assert requested["aid_status"] == "REQUESTED"

    reviewed = validate_success(api.review_aid(account["id"], {}, FINANCE_HEADERS))
    assert reviewed["aid_status"] == "UNDER_REVIEW"

    # ArtisticDirector programs the calendar, RegistrarStaff rosters and sweeps.
    event = validate_success(
        api.create_ensemble_event(
            F.ensemble_event_payload(
                ensemble["id"],
                kind="CONCERT",
                start_at=CONCERT_START,
                end_at=CONCERT_END,
                eligibility_window_start=ELIGIBILITY_WINDOW_START,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    participation = validate_success(
        api.create_event_participation(
            F.participation_payload(event["id"], member["id"]), REGISTRAR_HEADERS
        ),
        201,
    )
    assert participation["attendance_status"] == "NOT_RECORDED"

    sweep = validate_success(
        api.offer_expiry_sweep(season["id"], {}, REGISTRAR_HEADERS)
    )
    assert sweep["expired_count"] == 0
    assert sweep["promoted_count"] == 0

    reviewed_row = validate_success(
        api.review_eligibility(participation["id"], {}, DIRECTOR_HEADERS)
    )
    assert reviewed_row["attendance_index"] == 0.00
    assert reviewed_row["performance_eligibility"] == "INELIGIBLE"


# ---------------------------------------------------------------------------
# Shared reads, shared registration, shared clock
# ---------------------------------------------------------------------------

def test_reading_one_season_answers_two_hundred_for_all_five_roles(api):
    """The same season read is authorized for every one of the five roles.

    PRD §2.1: "If the headers are well formed but the acting role is not among the roles authorized for the endpoint in §4, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/shared_reads_registration_and_clock_are_open_to_their_declared_roles
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)
    member = X.create_member(api)
    panelist = X.create_panelist(api)

    every_role = [
        DIRECTOR_HEADERS,
        REGISTRAR_HEADERS,
        FINANCE_HEADERS,
        panelist_headers(panelist["id"]),
        guardian_headers(member["id"]),
    ]
    for headers in every_role:
        read = validate_success(api.get_season(season["id"], headers))
        assert read["id"] == season["id"]
        assert read["status"] == "PLANNING"


def test_panelist_may_read_the_audition_slot_it_sits_on(api):
    """A Panelist is authorized on every read endpoint other than the two musician routes.

    PRD §2.1: "A `Panelist` submits blind rubric sheets and nothing else; because reading a musician's `legal_name` would defeat blind evaluation, the `Panelist` role is the one role excluded from the musician-read and musician-list endpoints, and is authorized on every other read endpoint."

    Design: Corner/rbac/shared_reads_registration_and_clock_are_open_to_their_declared_roles
    """
    ctx = X.open_season_with_ensemble(api)
    panelists = X.create_panelists(api, count=3)
    slot = X.create_audition_slot(
        api, ctx["season"]["id"], [p["id"] for p in panelists]
    )

    headers = panelist_headers(panelists[0]["id"])
    read = validate_success(api.get_audition_slot(slot["id"], headers))
    assert read["id"] == slot["id"]
    assert read["instrument_focus"] == "CELLO"

    rows, meta = validate_paginated(api.list_audition_slots(headers))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == slot["id"]


def test_guardian_may_read_their_own_musician_row(api):
    """A Guardian reads the musician row they act for, because reads carry no ownership guard.

    PRD §2.1: "This ownership check guards exactly eight operations: registering an audition, submitting a rubric sheet, accepting a placement offer, declining a placement offer or waitlist claim, requesting financial aid, recording a payment, filing an excuse request, and submitting tour requirements."

    Design: Corner/rbac/shared_reads_registration_and_clock_are_open_to_their_declared_roles
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    member = X.create_member(api, legal_name="Ben Bow")

    read = validate_success(
        api.get_member(member["id"], guardian_headers(member["id"]))
    )
    assert read["id"] == member["id"]
    assert read["legal_name"] == "Ben Bow"
    assert read["enrollment_status"] == "PROSPECT"


def test_the_logical_clock_accepts_every_role_including_the_guardian(api):
    """Any of the five roles may move the logical clock, and the response echoes the new instant.

    PRD §2.5: "Any of the five roles may advance or rewind the clock by supplying a `current_utc` instant to the clock-setting capability; the call mutates no entity, and its response echoes the `current_utc` now in effect."

    Design: Corner/rbac/shared_reads_registration_and_clock_are_open_to_their_declared_roles
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    member = X.create_member(api)
    panelist = X.create_panelist(api)

    every_role = [
        DIRECTOR_HEADERS,
        REGISTRAR_HEADERS,
        FINANCE_HEADERS,
        panelist_headers(panelist["id"]),
        guardian_headers(member["id"]),
    ]
    for offset, headers in enumerate(every_role, start=1):
        instant = A.shift_instant(C.FIXTURE_CLOCK, hours=offset)
        echoed = validate_success(api.set_clock(F.clock_payload(instant), headers))
        A.assert_instants_equal(echoed["current_utc"], instant)


def test_registrar_staff_registers_an_audition_on_the_familys_behalf(api):
    """Audition registration is shared, so RegistrarStaff may file it without any ownership token.

    PRD §3.4: "Either a `Guardian` acting for their own musician or `RegistrarStaff` acting on a family's behalf registers an **Audition**, supplying the `member_id`, the `season_id`, a `declared_program` of 1 to 200 characters naming the solo repertoire, an `excerpt_ids` array of between one and six distinct excerpt code strings the musician has prepared, and an optional `scale_attested` flag defaulting to false that records whether the required scale set was attested at registration."

    Design: Corner/rbac/shared_reads_registration_and_clock_are_open_to_their_declared_roles
    """
    ctx = X.open_season_with_ensemble(api)
    member = X.create_member(api, legal_name="Ben Bow")

    registered = validate_success(
        api.create_audition(
            F.audition_payload(member["id"], ctx["season"]["id"]), REGISTRAR_HEADERS
        ),
        201,
    )
    assert registered["member_id"] == member["id"]
    assert registered["status"] == "REQUESTED"
    assert registered["slot_id"] is None


# ---------------------------------------------------------------------------
# An exclusive write is refused to every other role
# ---------------------------------------------------------------------------

def test_registrar_staff_cannot_create_a_season(api):
    """Season creation belongs to the ArtisticDirector, so RegistrarStaff is refused.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    validate_error(
        api.create_season(F.season_payload(name="Rogue Season"), REGISTRAR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, meta = validate_paginated(api.list_seasons(DIRECTOR_HEADERS))
    assert meta["total_count"] == 0


def test_artistic_director_cannot_register_a_musician(api):
    """Membership records belong to RegistrarStaff, so the ArtisticDirector is refused.

    PRD §2.1: "Attendance bookkeeping, the audition calendar, membership records and the operational offer-expiry sweep belong to `RegistrarStaff`, who never adjudicates and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    X.set_clock(api, C.FIXTURE_CLOCK)

    validate_error(
        api.create_member(
            F.member_payload(legal_name="Rogue Member"), DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, meta = validate_paginated(api.list_members(REGISTRAR_HEADERS))
    assert meta["total_count"] == 0


def test_registrar_staff_cannot_adjudicate_an_audition(api):
    """Adjudication belongs to the ArtisticDirector, so RegistrarStaff is refused before any state check.

    PRD §2.1: "Attendance bookkeeping, the audition calendar, membership records and the operational offer-expiry sweep belong to `RegistrarStaff`, who never adjudicates and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.adjudicated_audition(api)

    validate_error(
        api.adjudicate_audition(ctx["audition"]["id"], {}, REGISTRAR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_audition(api, ctx["audition"]["id"])
    assert after["version"] == ctx["audition"]["version"]


def test_artistic_director_cannot_submit_a_rubric_sheet(api):
    """Blind rubric sheets are the Panelist's alone, so the ArtisticDirector is refused.

    PRD §2.1: "A `Panelist` submits blind rubric sheets and nothing else; because reading a musician's `legal_name` would defeat blind evaluation, the `Panelist` role is the one role excluded from the musician-read and musician-list endpoints, and is authorized on every other read endpoint."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.scored_audition(api)

    validate_error(
        api.submit_panel_score(
            ctx["audition"]["id"],
            F.uniform_panel_score_payload(ctx["panelists"][0]["id"], 25),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    sheets = X.list_sheets(api, audition_id=ctx["audition"]["id"])
    assert len(sheets) == len(ctx["sheets"])


def test_finance_officer_cannot_create_a_placement(api):
    """Placements belong to the ArtisticDirector, so the FinanceOfficer is refused.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.adjudicated_audition(api)
    X.advance_season(api, ctx["season"]["id"], "PLACEMENT")

    validate_error(
        api.create_placement(
            F.placement_payload(
                ctx["audition"]["id"],
                ctx["ensemble"]["id"],
                X.ensemble_version(api, ctx["ensemble"]["id"]),
            ),
            FINANCE_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    assert X.list_placements(api, ensemble_id=ctx["ensemble"]["id"]) == []


def test_registrar_staff_cannot_accept_a_placement_offer(api):
    """Accepting an offer is the Guardian's action, so RegistrarStaff is refused.

    PRD §2.1: "If the headers are well formed but the acting role is not among the roles authorized for the endpoint in §4, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.placement_offer(api)

    validate_error(
        api.accept_placement(
            ctx["placement"]["id"],
            F.accept_payload(instrument_loan_requested=True),
            REGISTRAR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_placement(api, ctx["placement"]["id"])
    assert after["status"] == "OFFERED"
    assert X.list_seats(api, member_id=ctx["member"]["id"]) == []


def test_registrar_staff_cannot_finalize_a_tuition_assessment(api):
    """Tuition finalization belongs to the FinanceOfficer, so RegistrarStaff is refused.

    PRD §2.1: "Tuition finalization and the financial-aid workflow belong to `FinanceOfficer`, who cannot create members, cannot adjudicate, and — as §3.7 details — cannot fund an aid request they personally reviewed."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.placement_offer(api)
    account = X.sole_account(api, ctx["member"]["id"], ctx["season"]["id"])

    validate_error(
        api.finalize_assessment(account["id"], {}, REGISTRAR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_account(api, account["id"])
    assert after["assessment_variant"] == "PRELIMINARY"
    assert after["version"] == account["version"]


def test_finance_officer_cannot_record_a_family_payment(api):
    """Recording a payment is the Guardian's action, so the FinanceOfficer is refused.

    PRD §2.1: "If the headers are well formed but the acting role is not among the roles authorized for the endpoint in §4, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.accepted_placement(api)

    validate_error(
        api.record_payment(
            ctx["account"]["id"], F.payment_payload(1000), FINANCE_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_account(api, ctx["account"]["id"])
    assert after["payments_total_cents"] == 0
    assert after["balance_cents"] == ctx["account"]["balance_cents"]


def test_artistic_director_cannot_record_attendance(api):
    """Attendance bookkeeping belongs to RegistrarStaff, so the ArtisticDirector is refused.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = _seated_member_on_concert(api)

    validate_error(
        api.record_attendance(
            ctx["participation"]["id"],
            F.attendance_payload("PRESENT"),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_participation(api, ctx["participation"]["id"])
    assert after["attendance_status"] == "NOT_RECORDED"


def test_registrar_staff_cannot_run_an_eligibility_review(api):
    """Performance eligibility is the ArtisticDirector's judgement, so RegistrarStaff is refused.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = _seated_member_on_concert(api)

    validate_error(
        api.review_eligibility(ctx["participation"]["id"], {}, REGISTRAR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_participation(api, ctx["participation"]["id"])
    assert after["performance_eligibility"] == "UNREVIEWED"


def test_artistic_director_cannot_execute_the_aid_award_run(api):
    """The financial-aid waterfall belongs to the FinanceOfficer, so the ArtisticDirector is refused.

    PRD §2.1: "Tuition finalization and the financial-aid workflow belong to `FinanceOfficer`, who cannot create members, cannot adjudicate, and — as §3.7 details — cannot fund an aid request they personally reviewed."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    season = X.create_season(api)

    validate_error(
        api.aid_award_run(
            season["id"],
            F.aid_award_run_payload(season["version"]),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_season(api, season["id"])
    assert after["version"] == season["version"]
    assert after["aid_committed_cents"] == 0


def test_registrar_staff_cannot_rotate_the_chairs_of_a_section(api):
    """Chairs belong to the ArtisticDirector, so RegistrarStaff is refused before the roster gate.

    PRD §2.1: "Artistic judgement belongs to the `ArtisticDirector`, who owns seasons, ensembles, instrumentation sections, adjudication, placements, chairs, concert programming and performance eligibility — and who never records attendance and never moves money."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = X.open_season_with_ensemble(api)

    validate_error(
        api.rotate_chairs(
            ctx["quota"]["id"],
            F.rotate_chairs_payload(X.ensemble_version(api, ctx["ensemble"]["id"])),
            REGISTRAR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = X.read_section_quota(api, ctx["quota"]["id"])
    assert after["rotation_cycle_index"] == 0


def test_panelist_cannot_list_the_musicians(api):
    """The Panelist is the one role barred from the musician-list endpoint.

    PRD §2.1: "A `Panelist` submits blind rubric sheets and nothing else; because reading a musician's `legal_name` would defeat blind evaluation, the `Panelist` role is the one role excluded from the musician-read and musician-list endpoints, and is authorized on every other read endpoint."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    X.set_clock(api, C.FIXTURE_CLOCK)
    X.create_member(api, legal_name="Ada Strings")
    panelist = X.create_panelist(api)

    validate_error(
        api.list_members(panelist_headers(panelist["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_guardian_cannot_roster_a_musician_onto_an_event(api):
    """Rostering belongs to RegistrarStaff, so a Guardian is refused before the duplicate check.

    PRD §2.1: "If the headers are well formed but the acting role is not among the roles authorized for the endpoint in §4, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/an_exclusive_write_is_refused_to_every_other_role
    """
    ctx = _seated_member_on_concert(api)

    validate_error(
        api.create_event_participation(
            F.participation_payload(ctx["event"]["id"], ctx["member"]["id"]),
            guardian_headers(ctx["member"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    rows = X.list_participations(api, event_id=ctx["event"]["id"])
    assert len(rows) == 1
    assert X.read_event(api, ctx["event"]["id"])["participation_count"] == 1


# ---------------------------------------------------------------------------
# Segregation of duties keys on the acting X-User-ID, not on the role
# ---------------------------------------------------------------------------

def test_excuse_decision_refuses_the_registrar_who_recorded_the_absence(api):
    """The registrar who recorded the absence cannot decide its excuse, while a second registrar can.

    PRD §3.8: "`RegistrarStaff` then decides the pending excuse by supplying a `decision`, and the decision is segregated from the recording: the acting `X-User-ID` must not equal the `X-User-ID` that recorded the absence in the earlier attendance call on the same row, and must not equal an `excuse_decided_by_user_id` left by an earlier decision; either coincidence is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_id_not_on_the_role
    """
    ctx = X.accepted_placement(api)
    event = X.create_ensemble_event(
        api,
        ctx["ensemble"]["id"],
        kind="REHEARSAL",
        start_at=REHEARSAL_START,
        end_at=REHEARSAL_END,
    )
    participation = X.create_participation(api, event["id"], ctx["member"]["id"])

    X.set_clock(api, A.shift_instant(REHEARSAL_START, minutes=5))
    X.record_attendance(
        api, participation["id"], "ABSENCE_UNVERIFIED", REGISTRAR_HEADERS
    )
    filed = validate_success(
        api.request_excuse(
            participation["id"],
            F.excuse_request_payload("ILLNESS"),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    assert filed["attendance_status"] == "EXCUSE_PENDING"

    validate_error(
        api.decide_excuse(
            participation["id"],
            F.excuse_decision_payload("APPROVED"),
            REGISTRAR_HEADERS,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert (
        X.read_participation(api, participation["id"])["attendance_status"]
        == "EXCUSE_PENDING"
    )

    decided = validate_success(
        api.decide_excuse(
            participation["id"],
            F.excuse_decision_payload("APPROVED"),
            REGISTRAR_HEADERS_2,
        )
    )
    assert decided["attendance_status"] == "EXCUSED_ABSENT"
    assert decided["excuse_decided_by_user_id"] == REGISTRAR_USER_ID_2


def test_aid_award_run_refuses_the_officer_who_reviewed_the_request(api):
    """The officer who moved the request to UNDER_REVIEW cannot fund it, while a second officer can.

    PRD §3.7: "Segregation of duties bites first: the acting `X-User-ID` must not equal `aid_reviewed_by_user_id` on *any* account in the run queue, since the officer who reviewed a request may not be the officer who funds it, and a violation is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_keys_on_the_acting_user_id_not_on_the_role
    """
    ctx = _reviewed_aid_request(api, 40000)
    season_id = ctx["season"]["id"]

    validate_error(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    assert X.read_account(api, ctx["account"]["id"])["aid_status"] == "UNDER_REVIEW"

    run = validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )
    assert run["approved_count"] == 1
    assert run["aid_committed_cents"] == 30000
    assert run["aid_available_cents"] == 70000

    account = X.read_account(api, ctx["account"]["id"])
    assert account["aid_status"] == "APPROVED"
    assert account["aid_awarded_cents"] == 30000
    assert account["aid_awarded_by_user_id"] == FINANCE_USER_ID_2
    assert account["aid_reviewed_by_user_id"] == FINANCE_USER_ID


# ---------------------------------------------------------------------------
# Optimistic concurrency on a parent row's version
# ---------------------------------------------------------------------------

def test_placement_creation_rejects_a_stale_expected_ensemble_version(api):
    """A second offer replaying the token the first offer consumed is refused as stale.

    PRD §2.8: "In both cases, if the supplied value does not equal the ensemble's current `version`, the request is rejected with `ERR_STALE_ENSEMBLE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _placement_ready_season(api, member_count=2)
    ensemble_id = ctx["ensemble"]["id"]
    token = X.ensemble_version(api, ensemble_id)

    first = validate_success(
        api.create_placement(
            F.placement_payload(ctx["auditions"][0]["id"], ensemble_id, token),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert first["status"] == "OFFERED"

    validate_error(
        api.create_placement(
            F.placement_payload(ctx["auditions"][1]["id"], ensemble_id, token),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_STALE_ENSEMBLE_VERSION.value,
    )

    assert X.ensemble_version(api, ensemble_id) > token
    assert len(X.list_placements(api, ensemble_id=ensemble_id)) == 1


def test_placement_creation_admits_the_retry_on_the_freshly_read_ensemble_version(api):
    """The refused offer succeeds unchanged once it carries the ensemble's current version.

    PRD §2.8: "Creating a placement requires a non-optional `expected_ensemble_version` field in the request body, carrying the client's last observed `version` of the target ensemble."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _placement_ready_season(api, member_count=2)
    ensemble_id = ctx["ensemble"]["id"]
    stale = X.ensemble_version(api, ensemble_id)

    validate_success(
        api.create_placement(
            F.placement_payload(ctx["auditions"][0]["id"], ensemble_id, stale),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    validate_error(
        api.create_placement(
            F.placement_payload(ctx["auditions"][1]["id"], ensemble_id, stale),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_STALE_ENSEMBLE_VERSION.value,
    )

    retried = validate_success(
        api.create_placement(
            F.placement_payload(
                ctx["auditions"][1]["id"],
                ensemble_id,
                X.ensemble_version(api, ensemble_id),
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert retried["status"] == "OFFERED"
    assert retried["member_id"] == ctx["members"][1]["id"]
    assert X.read_ensemble(api, ensemble_id)["offered_count"] == 2


def test_chair_rotation_rejects_the_token_its_own_successful_run_invalidated(api):
    """The version that drove one rotation is stale for the next, because the rotation bumped it.

    PRD §2.8: "In both cases, if the supplied value does not equal the ensemble's current `version`, the request is rejected with `ERR_STALE_ENSEMBLE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _placement_ready_season(
        api,
        member_count=2,
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    _offer_and_accept(api, ctx, 0)
    _offer_and_accept(api, ctx, 1)
    ensemble_id = ctx["ensemble"]["id"]
    assert X.read_ensemble(api, ensemble_id)["roster_state"] == "SEATED"

    token = X.ensemble_version(api, ensemble_id)
    rotated = validate_success(
        api.rotate_chairs(
            ctx["quota"]["id"], F.rotate_chairs_payload(token), DIRECTOR_HEADERS
        )
    )
    assert rotated["rotation_cycle_index"] == 1

    validate_error(
        api.rotate_chairs(
            ctx["quota"]["id"], F.rotate_chairs_payload(token), DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_STALE_ENSEMBLE_VERSION.value,
    )
    assert X.read_section_quota(api, ctx["quota"]["id"])["rotation_cycle_index"] == 1


def test_chair_rotation_admits_the_retry_on_the_freshly_read_ensemble_version(api):
    """A second rotation runs as soon as the caller re-reads the owning ensemble's version.

    PRD §2.8: "Running a chair rotation on a section likewise requires a non-optional `expected_ensemble_version` carrying the last observed `version` of the section's owning ensemble."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _placement_ready_season(
        api,
        member_count=2,
        quota_overrides={"min_count": 1, "target_count": 2, "max_count": 2},
    )
    _offer_and_accept(api, ctx, 0)
    _offer_and_accept(api, ctx, 1)
    ensemble_id = ctx["ensemble"]["id"]

    stale = X.ensemble_version(api, ensemble_id)
    validate_success(
        api.rotate_chairs(
            ctx["quota"]["id"], F.rotate_chairs_payload(stale), DIRECTOR_HEADERS
        )
    )
    validate_error(
        api.rotate_chairs(
            ctx["quota"]["id"], F.rotate_chairs_payload(stale), DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_STALE_ENSEMBLE_VERSION.value,
    )

    retried = validate_success(
        api.rotate_chairs(
            ctx["quota"]["id"],
            F.rotate_chairs_payload(X.ensemble_version(api, ensemble_id)),
            DIRECTOR_HEADERS,
        )
    )
    assert retried["rotation_cycle_index"] == 2

    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["rotation_cycle_index"] == 2
    assert quota["filled_count"] == 2
    assert quota["balance_state"] == "FULL"
    A.assert_contiguous_chair_numbers(
        X.list_seats(api, section_quota_id=ctx["quota"]["id"])
    )


def test_aid_award_run_rejects_a_stale_expected_season_version(api):
    """Replaying the season version a completed award run consumed is refused as stale.

    PRD §2.8: "If it does not equal the season's current `version`, the run is rejected with `ERR_STALE_SEASON_VERSION` (412) — another award run, a rescission or a budget-affecting assessment will have moved `aid_committed_cents` and bumped the season's `version`, which means the officer's view of `aid_available_cents`, the very quantity the waterfall distributes, is stale."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _reviewed_aid_request(api, 40000)
    season_id = ctx["season"]["id"]
    token = X.season_version(api, season_id)

    run = validate_success(
        api.aid_award_run(
            season_id, F.aid_award_run_payload(token), FINANCE_HEADERS_2
        )
    )
    assert run["approved_count"] == 1

    validate_error(
        api.aid_award_run(
            season_id, F.aid_award_run_payload(token), FINANCE_HEADERS_2
        ),
        ApiErrorId.ERR_STALE_SEASON_VERSION.value,
    )

    season = X.read_season(api, season_id)
    assert season["version"] > token
    assert season["aid_committed_cents"] == 30000
    assert season["aid_available_cents"] == 70000
    A.assert_aid_pool_conserved(season)


def test_aid_award_run_admits_the_retry_on_the_freshly_read_season_version(api):
    """A retry carrying the season's current version runs, and funds nothing twice.

    PRD §2.8: "Executing the season's aid award run requires a non-optional `expected_season_version` field carrying the client's last observed `version` of the season."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_admit_the_retry
    """
    ctx = _reviewed_aid_request(api, 40000)
    season_id = ctx["season"]["id"]
    stale = X.season_version(api, season_id)

    validate_success(
        api.aid_award_run(
            season_id, F.aid_award_run_payload(stale), FINANCE_HEADERS_2
        )
    )
    validate_error(
        api.aid_award_run(
            season_id, F.aid_award_run_payload(stale), FINANCE_HEADERS_2
        ),
        ApiErrorId.ERR_STALE_SEASON_VERSION.value,
    )

    retried = validate_success(
        api.aid_award_run(
            season_id,
            F.aid_award_run_payload(X.season_version(api, season_id)),
            FINANCE_HEADERS_2,
        )
    )
    assert retried["approved_count"] == 0
    assert retried["denied_count"] == 0
    assert retried["aid_committed_cents"] == 30000
    assert retried["aid_available_cents"] == 70000

    account = X.read_account(api, ctx["account"]["id"])
    assert account["aid_awarded_cents"] == 30000
    assert account["balance_cents"] == 93223


# ---------------------------------------------------------------------------
# Cascade effects are visible to the very next read
# ---------------------------------------------------------------------------

def test_acceptance_counters_and_roster_states_are_correct_on_the_next_read(api):
    """One acceptance leaves the chair, the section fill, the roster posture and the season counter already correct.

    PRD §2.6: "Derived counters — a season's `ensemble_count` and `seated_ensemble_count`, an ensemble's `seated_count` and `offered_count`, a section's `filled_count`, a slot's `booked_count`, an audition's `submitted_score_count`, an event's `participation_count`, a musician's `unexcused_absence_count`, `tardy_count` and `effective_unexcused_count` — are recomputed as part of the same request that caused them to change, never lazily."

    Design: Corner/consistency_model/every_cascade_effect_is_visible_to_the_next_read_with_no_settling_step
    """
    ctx = X.placement_offer(api)

    accepted = validate_success(
        api.accept_placement(
            ctx["placement"]["id"],
            F.accept_payload(instrument_loan_requested=False),
            guardian_headers(ctx["member"]["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"

    read_back = X.read_placement(api, ctx["placement"]["id"])
    assert read_back["status"] == "ACCEPTED"
    assert read_back["instrument_loan_requested"] is False

    seats = X.list_seats(api, member_id=ctx["member"]["id"])
    assert len(seats) == 1
    assert seats[0]["status"] == "ACTIVE"
    assert seats[0]["chair_number"] == 1
    assert seats[0]["is_principal"] is True
    assert seats[0]["ranking_score"] == 80.00

    quota = X.read_section_quota(api, ctx["quota"]["id"])
    assert quota["filled_count"] == 1
    assert quota["balance_state"] == "FULL"

    ensemble = X.read_ensemble(api, ctx["ensemble"]["id"])
    assert ensemble["seated_count"] == 1
    assert ensemble["offered_count"] == 0
    assert ensemble["roster_state"] == "SEATED"

    season = X.read_season(api, ctx["season"]["id"])
    assert season["seated_ensemble_count"] == 1
    assert season["status"] == "IN_SEASON"


def test_acceptance_enrollment_and_tuition_account_need_no_settling_call(api):
    """The musician's enrollment hop and the freshly assessed tuition account are both readable immediately.

    PRD §2.6: "The system performs those propagations itself, immediately and synchronously, rather than waiting for a client to request them on each affected row."

    Design: Corner/consistency_model/every_cascade_effect_is_visible_to_the_next_read_with_no_settling_step
    """
    ctx = X.placement_offer(api)
    assert X.read_member(api, ctx["member"]["id"])["enrollment_status"] == "PROSPECT"

    validate_success(
        api.accept_placement(
            ctx["placement"]["id"],
            F.accept_payload(instrument_loan_requested=False),
            guardian_headers(ctx["member"]["id"]),
        )
    )

    member = X.read_member(api, ctx["member"]["id"])
    assert member["enrollment_status"] == "ENROLLED"
    assert member["standing_status"] == "CLEAR"

    rows, meta = validate_paginated(
        api.list_tuition_accounts(
            FINANCE_HEADERS, params={"member_id": ctx["member"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    account = rows[0]
    assert account["assessment_variant"] == "PRELIMINARY"
    assert account["assessed_cents"] == 123223
    assert account["balance_cents"] == 123223
    assert account["billing_status"] == "CURRENT"
    A.assert_balance_identity(account)
