"""Nurture dispatch: which gate refuses first, and the two edges of the 30-day frequency window."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import community_manager_headers

FIRST_WAVE_INSTANT = "2026-08-01T00:00:00Z"
THIRTY_DAYS_LATER = "2026-08-31T00:00:00Z"


def _paused_sole_member_and_an_oversized_campaign(api):
    """The only audience member is paused, and the campaign's ceiling outruns the program quota."""
    program = fx.create_program(api, send_quota_total=2)
    member = fx.subscribed_member(
        api, program["id"], "paused@example.com", frequency_cap_per_30d=4
    )
    fx.change_consent(api, member["id"], "PAUSE")
    campaign = fx.scheduled_campaign(
        api, program["id"], FIRST_WAVE_INSTANT, name="August talent digest", max_sends=5
    )
    return program, member, campaign


def test_a_paused_only_audience_reports_the_consent_gate_and_not_the_quota_gate(api):
    """PRD §3.7: "The audience is then assembled and two further gates apply: at least one member
    of that audience must be in `SUBSCRIBED`, refused otherwise with `ERR_NO_CONSENTED_AUDIENCE`,
    and the campaign's `max_sends` must be no greater than the program's `send_quota_total` less its
    `send_quota_used`, refused otherwise with `ERR_SEND_QUOTA_EXCEEDED`."
    PRD §2.9: "26. At least one member of a dispatch audience must be `SUBSCRIBED`, else
    `ERR_NO_CONSENTED_AUDIENCE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_consent_safety_outranks_send_quota_fiscal
    """
    program, _, campaign = _paused_sole_member_and_an_oversized_campaign(api)

    refused = api.dispatch_nurture_campaign(campaign["id"], community_manager_headers())

    validate_error(refused, ApiErrorId.NO_CONSENTED_AUDIENCE, 409)
    unchanged = fx.read_campaign(api, campaign["id"])
    assert unchanged["state"] == "SCHEDULED", unchanged
    assert unchanged["dispatched_at"] is None, unchanged
    assert unchanged["audience_size"] == 0, unchanged
    assert unchanged["sent_count"] == 0, unchanged
    assert unchanged["suppressed_consent_count"] == 0, unchanged
    assert fx.list_nurture_sends(api, campaign_id=campaign["id"]) == []
    assert fx.read_program(api, program["id"])["send_quota_used"] == 0


def test_resuming_the_only_member_uncovers_the_send_quota_ceiling(api):
    """PRD §2.9: "49. A campaign's `max_sends` must not exceed the program's remaining send quota,
    else `ERR_SEND_QUOTA_EXCEEDED` (409)."
    PRD §3.7: "Note carefully that the quota check compares the campaign's *ceiling* against
    remaining quota, not the number of messages that will actually go out."
    PRD §3.7: "`RESUME` requires `PAUSED` and moves the member `PAUSED → SUBSCRIBED`; either action
    on the wrong starting status is refused with `ERR_CONSENT_TRANSITION_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_consent_safety_outranks_send_quota_fiscal
    """
    program, member, campaign = _paused_sole_member_and_an_oversized_campaign(api)

    resumed = fx.change_consent(api, member["id"], "RESUME")
    refused = api.dispatch_nurture_campaign(campaign["id"], community_manager_headers())

    assert resumed["consent_status"] == "SUBSCRIBED", resumed
    validate_error(refused, ApiErrorId.SEND_QUOTA_EXCEEDED, 409)
    unchanged = fx.read_campaign(api, campaign["id"])
    assert unchanged["state"] == "SCHEDULED", unchanged
    assert unchanged["dispatched_at"] is None, unchanged
    assert fx.list_nurture_sends(api, campaign_id=campaign["id"]) == []
    assert fx.read_program(api, program["id"])["send_quota_used"] == 0


def _two_members_after_a_first_wave(api):
    """One member capped at a single message per window, one capped at two, both already sent to."""
    program = fx.create_program(api, send_quota_total=10)
    first = fx.subscribed_member(api, program["id"], "m1@example.com", frequency_cap_per_30d=1)
    second = fx.subscribed_member(api, program["id"], "m2@example.com", frequency_cap_per_30d=2)
    wave = fx.scheduled_campaign(
        api, program["id"], FIRST_WAVE_INSTANT, name="Wave 1", max_sends=2
    )
    dispatched = fx.dispatch_campaign(api, wave["id"])
    return program, first, second, dispatched


def test_the_opening_wave_sends_to_both_members_on_an_empty_window(api):
    """PRD §3.7: "The evaluated members are walked in that strict order, and each one produces
    exactly one `NurtureSend` row."
    PRD §3.7: "A running counter assigns `sequence_no` starting at 1 for the first member
    evaluated."
    PRD §3.7: "The campaign's `audience_size` becomes the number of rows written in any outcome,
    `sent_count` the number of `SENT` rows, `suppressed_consent_count` the number of
    `SUPPRESSED_CONSENT` rows and `suppressed_frequency_count` the number of
    `SUPPRESSED_FREQUENCY` rows."

    Design: Difficulty/boundary_precision_check/frequency_cap_suppresses_at_exactly_the_cap_and_window_lower_bound_is_exclusive
    """
    _, first, second, wave = _two_members_after_a_first_wave(api)

    assert wave["state"] == "DISPATCHED", wave
    assert wave["audience_size"] == 2, wave
    assert wave["sent_count"] == 2, wave
    assert wave["suppressed_frequency_count"] == 0, wave
    assert wave["suppressed_consent_count"] == 0, wave
    rows = fx.list_nurture_sends(api, campaign_id=wave["id"])
    assert [row["sequence_no"] for row in rows] == [1, 2], rows
    assert [row["member_id"] for row in rows] == [first["id"], second["id"]], rows
    assert [row["outcome"] for row in rows] == ["SENT", "SENT"], rows
    assert [row["window_send_count_at_eval"] for row in rows] == [0, 0], rows
    assert all(row["sent_at"] is not None for row in rows), rows


def test_a_window_count_equal_to_the_cap_suppresses_while_one_below_still_sends(api):
    """PRD §3.7: "The verdict then follows a pinned check order in which **consent is examined
    before frequency**: if the member's `consent_status` is anything other than `SUBSCRIBED`, the
    `outcome` is `SUPPRESSED_CONSENT`; otherwise, if the window count is greater than or equal to
    the member's `frequency_cap_per_30d`, the `outcome` is `SUPPRESSED_FREQUENCY`; otherwise the
    `outcome` is `SENT`."
    PRD §3.7: "The comparison against the cap is inclusive — a member whose cap is 4 and who has
    already received 4 messages in the window is suppressed."
    PRD §3.7: "The program's `send_quota_used` rises by the number of `SENT` rows only — suppressed
    evaluations consume no quota — and `send_quota_used` is by definition the count of `SENT` rows
    across every campaign of that program."

    Design: Difficulty/boundary_precision_check/frequency_cap_suppresses_at_exactly_the_cap_and_window_lower_bound_is_exclusive
    """
    program, first, second, _ = _two_members_after_a_first_wave(api)
    second_wave = fx.scheduled_campaign(
        api, program["id"], FIRST_WAVE_INSTANT, name="Wave 2", max_sends=2
    )

    dispatched = fx.dispatch_campaign(api, second_wave["id"])

    assert dispatched["audience_size"] == 2, dispatched
    assert dispatched["sent_count"] == 1, dispatched
    assert dispatched["suppressed_frequency_count"] == 1, dispatched
    assert dispatched["suppressed_consent_count"] == 0, dispatched
    rows = fx.list_nurture_sends(api, campaign_id=second_wave["id"])
    capped, headroom = rows
    assert capped["member_id"] == first["id"], rows
    assert capped["outcome"] == "SUPPRESSED_FREQUENCY", capped
    assert capped["window_send_count_at_eval"] == 1, capped
    assert capped["sent_at"] is None, capped
    assert headroom["member_id"] == second["id"], rows
    assert headroom["outcome"] == "SENT", headroom
    assert headroom["window_send_count_at_eval"] == 1, headroom
    assert headroom["sent_at"] is not None, headroom
    assert fx.read_program(api, program["id"])["send_quota_used"] == 3


def test_a_send_exactly_thirty_days_old_drops_out_and_frees_the_capped_member(api):
    """PRD §3.7: "For each member, the service counts that member's existing send-evaluation rows
    whose `outcome` is `SENT` and whose `sent_at` is **strictly later** than the logical clock minus
    30 days — a send that landed exactly 30 days ago is outside the window — and records that count
    on the new row as `window_send_count_at_eval`, capturing the value as it stood *before* this row
    was written."
    PRD §3.7: "For every row whose outcome was `SENT`, the member's `sent_count_total` rises by 1
    and their `last_sent_at` becomes the logical clock."

    Design: Difficulty/boundary_precision_check/frequency_cap_suppresses_at_exactly_the_cap_and_window_lower_bound_is_exclusive
    """
    program, first, second, _ = _two_members_after_a_first_wave(api)
    second_wave = fx.scheduled_campaign(
        api, program["id"], FIRST_WAVE_INSTANT, name="Wave 2", max_sends=2
    )
    fx.dispatch_campaign(api, second_wave["id"])
    fx.move_clock(api, THIRTY_DAYS_LATER)
    third_wave = fx.scheduled_campaign(
        api, program["id"], THIRTY_DAYS_LATER, name="Wave 3", max_sends=2
    )

    dispatched = fx.dispatch_campaign(api, third_wave["id"])

    assert dispatched["sent_count"] == 2, dispatched
    assert dispatched["suppressed_frequency_count"] == 0, dispatched
    rows = fx.list_nurture_sends(api, campaign_id=third_wave["id"])
    assert [row["outcome"] for row in rows] == ["SENT", "SENT"], rows
    assert [row["window_send_count_at_eval"] for row in rows] == [0, 0], rows
    capped_member = fx.read_member(api, first["id"])
    headroom_member = fx.read_member(api, second["id"])
    assert capped_member["sent_count_total"] == 2, capped_member
    assert capped_member["last_sent_at"].startswith("2026-08-31T00:00:00"), capped_member
    assert headroom_member["sent_count_total"] == 3, headroom_member
    assert headroom_member["last_sent_at"].startswith("2026-08-31T00:00:00"), headroom_member
    assert fx.read_program(api, program["id"])["send_quota_used"] == 5
