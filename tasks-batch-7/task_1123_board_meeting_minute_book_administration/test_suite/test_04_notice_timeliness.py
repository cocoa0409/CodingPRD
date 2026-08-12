"""Notice timeliness: type-branch selection and the inclusive deadline boundary."""
from datetime import datetime, timezone

from test_helpers import (
    add_director,
    create_corporation,
    get_success_data,
    schedule_meeting,
    send_notices,
    set_clock,
    setup_corporation_with_adopted_bylaws,
    validate_paginated,
    SECRETARY,
)
from test_helpers import api_client


def _parse_iso_second(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp and truncate to second precision
    (PRD §2.8: "All timestamps are compared at second precision")."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def _get_notice_for_meeting(api, meeting_id: str) -> dict:
    resp = api.list_meeting_notices(SECRETARY, params={"meeting_id": meeting_id})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 notice, got {len(data)}"
    return data[0]


class TestNoticeTimelinessTypeBranching:
    """Difficulty instance: notice_timeliness_type_branching.

    Same send instant 2026-06-17T10:00:00Z is LATE for a REGULAR meeting at
    2026-06-20T10:00 (10-day deadline 2026-06-10T10:00) but TIMELY for a
    SPECIAL meeting at 2026-06-20T14:00 (3-day deadline 2026-06-17T14:00).
    """

    def _setup(self, api):
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp N", incorporation_state="CA")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        m_a = schedule_meeting(
            corp["id"], d1["id"], meeting_type="REGULAR", scheduled_start="2026-06-20T10:00:00Z"
        )
        m_b = schedule_meeting(
            corp["id"],
            d1["id"],
            meeting_type="SPECIAL",
            scheduled_start="2026-06-20T14:00:00Z",
        )
        set_clock("2026-06-17T10:00:00Z")
        send_notices(m_a["id"])
        send_notices(m_b["id"])
        return corp, m_a, m_b

    def test_regular_branch_uses_notice_days_regular(self, api):
        """PRD §3.4: "`required_notice_days` is snapshotted from the adopted
        bylaws as `notice_days_special` for a `SPECIAL` meeting and
        `notice_days_regular` for `REGULAR` or `ANNUAL`; `deadline_at` is the
        scheduled start moved back by that many full days, each day counted as
        86,400 seconds; and `is_timely` records whether the notice went out on
        or before its deadline."

        Design: Difficulty/combinatorial_formula/notice_timeliness_type_branching
        """
        _corp, m_a, _m_b = self._setup(api)
        n_a = _get_notice_for_meeting(api, m_a["id"])
        assert n_a["required_notice_days"] == 10
        assert _parse_iso_second(n_a["deadline_at"]) == _parse_iso_second("2026-06-10T10:00:00Z")
        assert n_a["is_timely"] is False, (
            f"REGULAR branch: sent 2026-06-17T10:00 > deadline 2026-06-10T10:00, got {n_a['is_timely']}"
        )

    def test_special_branch_uses_notice_days_special(self, api):
        """PRD §3.4: "`required_notice_days` is snapshotted from the adopted
        bylaws as `notice_days_special` for a `SPECIAL` meeting and
        `notice_days_regular` for `REGULAR` or `ANNUAL`; `deadline_at` is the
        scheduled start moved back by that many full days, each day counted as
        86,400 seconds; and `is_timely` records whether the notice went out on
        or before its deadline."

        Design: Difficulty/combinatorial_formula/notice_timeliness_type_branching
        """
        _corp, _m_a, m_b = self._setup(api)
        n_b = _get_notice_for_meeting(api, m_b["id"])
        assert n_b["required_notice_days"] == 3
        assert _parse_iso_second(n_b["deadline_at"]) == _parse_iso_second("2026-06-17T14:00:00Z")
        assert n_b["is_timely"] is True, (
            f"SPECIAL branch: sent 2026-06-17T10:00 <= deadline 2026-06-17T14:00, got {n_b['is_timely']}"
        )


class TestNoticeSentExactlyAtDeadline:
    """Difficulty instance: notice_sent_exactly_at_deadline."""

    def test_notice_sent_exactly_at_deadline_is_timely(self, api):
        """PRD §3.4: "`is_timely` records whether the notice went out on or
        before its deadline — dispatch exactly at the deadline counts as
        timely."

        Design: Difficulty/boundary_precision_check/notice_sent_exactly_at_deadline
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp B2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        m = schedule_meeting(
            corp["id"], d1["id"], meeting_type="REGULAR", scheduled_start="2026-06-20T10:00:00Z"
        )
        set_clock("2026-06-10T10:00:00Z")
        send_notices(m["id"])
        n = _get_notice_for_meeting(api, m["id"])
        assert _parse_iso_second(n["deadline_at"]) == _parse_iso_second("2026-06-10T10:00:00Z")
        assert _parse_iso_second(n["sent_at"]) == _parse_iso_second("2026-06-10T10:00:00Z"), (
            f"expected sent_at at the logical clock, got {n['sent_at']}"
        )
        assert n["is_timely"] is True, "inclusive deadline: sent_at <= deadline_at"

    def test_meeting_transitions_to_noticed(self, api):
        """PRD §3.4: "The meeting pins `bylaws_id_at_notice` to the adopted
        bylaws' `id` and moves `SCHEDULED` → `NOTICED`."

        Design: Difficulty/boundary_precision_check/notice_sent_exactly_at_deadline
        """
        corp, bylaws = setup_corporation_with_adopted_bylaws(name="Corp B2b")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        m = schedule_meeting(
            corp["id"], d1["id"], meeting_type="REGULAR", scheduled_start="2026-06-20T10:00:00Z"
        )
        set_clock("2026-06-10T10:00:00Z")
        send_notices(m["id"])
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "NOTICED"
        assert after["bylaws_id_at_notice"] == bylaws["id"]
