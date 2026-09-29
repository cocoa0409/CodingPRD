"""Three bookable resources, three different interval predicates."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import assert_posture
from test_helpers.test_users import make_analyst_headers, make_auditor_headers, make_counsel_headers

INVESTIGATOR = "counsel-05"
SITTING_START = "2026-08-10T09:00:00Z"
SITTING_END = "2026-08-10T11:00:00Z"


def _firm_with_one_sitting_hearing(client, extra_respondents=1, room="ROOM-A"):
    """A hearing already holding `room` from 09:00 to 11:00, plus waiting cases."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]

    sitting_respondent = fixtures.affiliate_new_salesperson(
        client, brokerage_id, broker_id, "Rae Field"
    )
    case_a = fixtures.file_complaint(
        client, sitting_respondent["id"], "AGENCY_DISCLOSURE", 800000, "Ora Buyer"
    )
    fixtures.dispose_complaint(client, case_a["id"], "INVESTIGATE", counsel_user_id=INVESTIGATOR)
    fixtures.dispose_complaint(
        client, case_a["id"], "PROBABLE_CAUSE", counsel_user_id=INVESTIGATOR
    )
    sitting = fixtures.schedule_hearing(
        client,
        case_a["id"],
        "chair-01",
        SITTING_START,
        SITTING_END,
        room,
        counsel_user_id=INVESTIGATOR,
    )

    waiting = []
    for name in ("Ken Ito", "Lin Ozu")[:extra_respondents]:
        respondent = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, name)
        case = fixtures.file_complaint(
            client, respondent["id"], "MISREPRESENTATION", 900000, "Ivo Renter"
        )
        fixtures.dispose_complaint(client, case["id"], "INVESTIGATE", counsel_user_id=INVESTIGATOR)
        fixtures.dispose_complaint(
            client, case["id"], "PROBABLE_CAUSE", counsel_user_id=INVESTIGATOR
        )
        waiting.append({"respondent": respondent, "complaint": case})
    return {"sitting": sitting, "sitting_complaint": case_a, "waiting": waiting}


def _try_slot(client, complaint_id, start_at, end_at, room="ROOM-A", chair="chair-02"):
    return client.schedule_hearing(
        complaint_id,
        factories.hearing_payload(chair, start_at, end_at, room),
        make_counsel_headers(INVESTIGATOR),
    )


class TestHearingRoomBufferedExclusion:
    """The room needs thirty minutes of turnover on whichever side it meets."""

    def test_exact_adjacency_is_a_conflict(self, client):
        """A gap of zero is not a gap at all as far as a room is concerned.

        The PRD says "For every other hearing in the same `hearing_room` whose
        `status` is `SCHEDULED`, `CONVENED` or `CONTINUED`, the new slot must
        either begin at or after that hearing's `scheduled_end_at` plus 30
        minutes, or end at least 30 minutes before that hearing's
        `scheduled_start_at`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_exclusion_rejects_adjacency_and_a_29_minute_gap
        """
        world = _firm_with_one_sitting_hearing(client)
        complaint_id = world["waiting"][0]["complaint"]["id"]

        validate_error(
            _try_slot(client, complaint_id, SITTING_END, "2026-08-10T12:00:00Z"),
            "ERR_HEARING_ROOM_CONFLICT",
            expected_status=409,
        )
        assert fixtures.read_complaint(client, complaint_id)["status"] == "PROBABLE_CAUSE"

    def test_a_twenty_nine_minute_gap_is_still_a_conflict(self, client):
        """One minute short of the buffer is still short of the buffer.

        The PRD says "Back-to-back booking with a gap of exactly zero is
        therefore a **conflict**, while a gap of exactly 30 minutes is
        permitted."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_exclusion_rejects_adjacency_and_a_29_minute_gap
        """
        world = _firm_with_one_sitting_hearing(client)
        complaint_id = world["waiting"][0]["complaint"]["id"]

        validate_error(
            _try_slot(client, complaint_id, "2026-08-10T11:29:00Z", "2026-08-10T12:29:00Z"),
            "ERR_HEARING_ROOM_CONFLICT",
        )

        hearings, meta = validate_paginated(
            client.list_hearings(complaint_id, make_analyst_headers())
        )
        assert hearings == [], "neither refusal created a hearing"
        assert meta["total_count"] == 0

    def test_exactly_thirty_minutes_of_turnover_is_accepted(self, client):
        """The permitted boundary, taken on the later side of the sitting slot.

        The PRD says "A violation answers `ERR_HEARING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_exclusion_rejects_adjacency_and_a_29_minute_gap
        """
        world = _firm_with_one_sitting_hearing(client)
        complaint_id = world["waiting"][0]["complaint"]["id"]
        validate_error(
            _try_slot(client, complaint_id, "2026-08-10T11:29:00Z", "2026-08-10T12:29:00Z"),
            "ERR_HEARING_ROOM_CONFLICT",
        )

        accepted = validate_success(
            _try_slot(client, complaint_id, "2026-08-10T11:30:00Z", "2026-08-10T12:30:00Z"),
            expected_status=201,
        )
        assert accepted["hearing_room"] == "ROOM-A"
        assert accepted["continuance_count"] == 0
        assert fixtures.read_complaint(client, complaint_id)["status"] == "HEARING_SCHEDULED"

        sitting = validate_success(
            client.get_hearing(world["sitting"]["id"], make_analyst_headers())
        )
        assert sitting["status"] == "SCHEDULED"
        assert sitting["scheduled_start_at"] == SITTING_START
        assert sitting["scheduled_end_at"] == SITTING_END
        assert sitting["continuance_count"] == 0

    def test_the_buffer_is_symmetric_on_the_earlier_side(self, client):
        """A slot ending exactly thirty minutes before the sitting one is clean.

        The PRD says "or end at least 30 minutes before that hearing's
        `scheduled_start_at`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_buffered_exclusion_rejects_adjacency_and_a_29_minute_gap
        """
        world = _firm_with_one_sitting_hearing(client, extra_respondents=2)
        earlier_case = world["waiting"][1]["complaint"]["id"]

        accepted = validate_success(
            _try_slot(client, earlier_case, "2026-08-10T07:00:00Z", "2026-08-10T08:30:00Z"),
            expected_status=201,
        )
        assert accepted["hearing_room"] == "ROOM-A"
        assert accepted["scheduled_end_at"] == "2026-08-10T08:30:00Z"
        assert fixtures.read_complaint(client, earlier_case)["status"] == "HEARING_SCHEDULED"


class TestPanelChairHalfOpenExclusion:
    """A person carries no buffer, so the room's forbidden adjacency is legal."""

    def test_a_one_minute_intersection_double_books_the_chair(self, client):
        """Half-open windows that overlap by a minute still overlap.

        The PRD says "For every other hearing with the same
        `panel_chair_user_id` whose `status` is `SCHEDULED`, `CONVENED` or
        `CONTINUED`, the half-open intervals from start inclusive to end
        exclusive must simply not intersect."

        Design: Difficulty/resource_temporal_overlap/panel_chair_half_open_exclusion_allows_the_very_adjacency_the_room_rule_forbids
        """
        world = _firm_with_one_sitting_hearing(client)
        complaint_id = world["waiting"][0]["complaint"]["id"]

        validate_error(
            _try_slot(
                client,
                complaint_id,
                "2026-08-10T10:59:00Z",
                "2026-08-10T12:00:00Z",
                room="ROOM-B",
                chair="chair-01",
            ),
            "ERR_PANEL_CHAIR_DOUBLE_BOOKED",
            expected_status=409,
        )
        assert fixtures.read_complaint(client, complaint_id)["status"] == "PROBABLE_CAUSE"

    def test_the_chair_may_sit_back_to_back_across_two_rooms(self, client):
        """The very start instant the room rule rejects is accepted for a person.

        The PRD says "A new hearing that begins at the exact instant the chair's
        previous hearing ends is therefore **permitted**."

        Design: Difficulty/resource_temporal_overlap/panel_chair_half_open_exclusion_allows_the_very_adjacency_the_room_rule_forbids
        """
        world = _firm_with_one_sitting_hearing(client)
        complaint_id = world["waiting"][0]["complaint"]["id"]

        accepted = validate_success(
            _try_slot(
                client,
                complaint_id,
                SITTING_END,
                "2026-08-10T12:00:00Z",
                room="ROOM-B",
                chair="chair-01",
            ),
            expected_status=201,
        )
        assert accepted["panel_chair_user_id"] == "chair-01"
        assert accepted["hearing_room"] == "ROOM-B"
        assert accepted["scheduled_start_at"] == SITTING_END

        sitting = validate_success(
            client.get_hearing(world["sitting"]["id"], make_analyst_headers())
        )
        assert sitting["status"] == "SCHEDULED"
        assert fixtures.read_complaint(client, complaint_id)["status"] == "HEARING_SCHEDULED"


AUDITOR = "auditor-42"
COLLEAGUE = "auditor-43"
WINDOW_ONE = ("2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z")
WINDOW_TWO = ("2026-08-10T13:00:00Z", "2026-08-11T13:00:00Z")
THIRD_WINDOW = ("2026-08-10T15:00:00Z", "2026-08-10T18:00:00Z")
ADJACENT_WINDOW = ("2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z")


def _account_with_two_overlapping_windows_for_one_auditor(client):
    """One escrow account, two legally overlapping fieldwork windows for `AUDITOR`."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    account_id = firm["account"]["id"]
    first = fixtures.schedule_audit(
        client,
        account_id,
        AUDITOR,
        fieldwork_start_at=WINDOW_ONE[0],
        fieldwork_end_at=WINDOW_ONE[1],
    )
    second = fixtures.schedule_audit(
        client,
        account_id,
        AUDITOR,
        fieldwork_start_at=WINDOW_TWO[0],
        fieldwork_end_at=WINDOW_TWO[1],
    )
    return {
        "brokerage_id": firm["brokerage"]["id"],
        "account_id": account_id,
        "first": first,
        "second": second,
    }


def _try_window(client, account_id, auditor_user_id, window):
    return client.schedule_audit(
        account_id,
        factories.audit_payload(auditor_user_id, "BOOK", "2026-08-31", window[0], window[1]),
        make_auditor_headers(auditor_user_id),
    )


class TestAuditorWindowCapacityIsAnAggregateCount:
    """Two overlapping windows are fine; the third one is refused."""

    def test_two_overlapping_windows_for_one_auditor_are_legal(self, client):
        """A pairwise-exclusion reading would already have rejected the second.

        The PRD says "Auditor capacity is checked here, at scheduling time, and
        it is an **aggregate count rather than a pairwise exclusion**: count the
        other audits sharing the same `auditor_user_id` whose `status` is any of
        `SCHEDULED`, `FIELDWORK`, `FINDINGS_ISSUED`, `REMEDIATION_ORDERED` or
        `VERIFYING` and whose half-open fieldwork window intersects the requested
        window; that count must be strictly below 2."

        Design: Difficulty/resource_temporal_overlap/auditor_window_capacity_two_is_an_aggregate_count_not_pairwise_exclusion
        """
        world = _account_with_two_overlapping_windows_for_one_auditor(client)
        assert world["first"]["status"] == "SCHEDULED"
        assert world["second"]["status"] == "SCHEDULED"
        assert world["second"]["auditor_user_id"] == AUDITOR
        assert world["second"]["remediation_round"] == 0

    def test_the_third_intersecting_window_is_refused(self, client):
        """Two other intersecting audits is not strictly below two.

        The PRD says "Two overlapping windows are therefore acceptable and a
        third overlapping window is refused with `ERR_AUDITOR_WINDOW_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/auditor_window_capacity_two_is_an_aggregate_count_not_pairwise_exclusion
        """
        world = _account_with_two_overlapping_windows_for_one_auditor(client)

        validate_error(
            _try_window(client, world["account_id"], AUDITOR, THIRD_WINDOW),
            "ERR_AUDITOR_WINDOW_CAPACITY",
            expected_status=409,
        )

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "OPEN"
        assert account["shortage_cents"] == 0
        assert_posture(fixtures.read_brokerage(client, world["brokerage_id"]), "COMPLIANT")

    def test_the_capacity_is_scoped_to_the_auditor_and_ignores_adjacency(self, client):
        """A colleague takes the refused window, and a touching window is free.

        The PRD says "Windows that merely touch — one ending exactly where the
        next begins — do not intersect under half-open semantics and do not
        count."

        Design: Difficulty/resource_temporal_overlap/auditor_window_capacity_two_is_an_aggregate_count_not_pairwise_exclusion
        """
        world = _account_with_two_overlapping_windows_for_one_auditor(client)
        account_id = world["account_id"]
        validate_error(
            _try_window(client, account_id, AUDITOR, THIRD_WINDOW),
            "ERR_AUDITOR_WINDOW_CAPACITY",
        )

        colleague = validate_success(
            _try_window(client, account_id, COLLEAGUE, THIRD_WINDOW), expected_status=201
        )
        assert colleague["auditor_user_id"] == COLLEAGUE
        assert colleague["status"] == "SCHEDULED"

        touching = validate_success(
            _try_window(client, account_id, AUDITOR, ADJACENT_WINDOW), expected_status=201
        )
        assert touching["status"] == "SCHEDULED"
        assert touching["fieldwork_start_at"] == WINDOW_TWO[1]

        audits, meta = validate_paginated(
            client.list_trust_audits(
                make_analyst_headers(), params={"trust_account_id": account_id}
            )
        )
        assert meta["total_count"] == 4, "the refused request created nothing"
        assert len(audits) == 4
