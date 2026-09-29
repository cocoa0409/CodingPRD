"""Immediate visibility of writes and their cascades, and the inertness of the clock.

Both tests translate the single instance of the corner design index's
``consistency_model`` section: a write's cascade is readable in the very next
read, while a stored derived field only moves when something writes it.
"""

from test_helpers import (
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    ApiClient,
    ApiErrorId,
    assertions,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_INSIDE_BLACKOUT = "2026-08-12T00:00:00Z"


def _approved_public_answer(api: ApiClient):
    """An issuer whose blackout window opens on 2026-08-10, with one APPROVED draft.

    The draft is authored and approved while the clock still reads
    2026-08-01T00:00:00Z, so the stored posture is OPEN at approval time.
    """
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="IMM",
        legal_name="Immediate Consistency Corp",
        shares_outstanding=1000000,
        blackout_window_start="2026-08-10T00:00:00Z",
        blackout_window_end="2026-08-20T00:00:00Z",
    )
    assert company["disclosure_posture"] == "OPEN"

    holder = fixtures.create_contact(
        api,
        company["id"],
        contact_type="INSTITUTIONAL_HOLDER",
        display_name="Immediate Holder",
        email="imm@funds.test",
        shares_held=20000,
    )
    pipeline = fixtures.build_answer_pipeline(
        api,
        company["id"],
        holder["id"],
        stage="approved",
        topic_category="OTHER",
        subject="Answered across a clock move.",
        body_text="Only public material here.",
        disclosure_class="PUBLIC_DOMAIN",
    )
    assert pipeline["draft"]["status"] == "APPROVED"
    return company, holder, pipeline


def test_clock_move_alone_leaves_the_stored_posture_open_and_the_send_lands_at_once(
    api: ApiClient,
):
    """PRD §2.4: "Moving the clock mutates no entity and triggers no recomputation of any derived field."
    PRD §2.7: "Advancing the logical clock into or out of a blackout window does nothing on its own."
    PRD §3.6: "A successful dispatch drives the parent inquiry `AWAITING_APPROVAL` → `ANSWERED` with `answered_at` stamped from the logical clock and the inquiry's `version` incremented, and then recounts the issuer's `open_inquiry_count` — `ANSWERED` being the one status outside the open set — incrementing the issuer's `version` by 1 as well."
    PRD §2.11: "Every cascade in this system completes inside the request that triggered it — there is no deferred or eventual reconciliation."

    Design: Corner/consistency_model/writes_and_their_cascades_are_visible_immediately
    """
    company, _holder, pipeline = _approved_public_answer(api)

    before = validate_success(api.get_company(company["id"], IR_ADMIN))
    assert before["disclosure_posture"] == "OPEN"
    assertions.assert_ts_equals(
        before["posture_recomputed_at"], CLOCK_START, "posture_recomputed_at"
    )

    fixtures.set_clock(api, CLOCK_INSIDE_BLACKOUT)

    after_clock_move = validate_success(api.get_company(company["id"], IR_ADMIN))
    assert after_clock_move["disclosure_posture"] == "OPEN"
    assert after_clock_move["version"] == before["version"]
    assert after_clock_move["open_inquiry_count"] == before["open_inquiry_count"]
    assertions.assert_ts_equals(
        after_clock_move["posture_recomputed_at"], CLOCK_START, "posture_recomputed_at"
    )
    assertions.assert_ts_equals(
        after_clock_move["updated_at"], before["updated_at"], "updated_at"
    )

    sent = validate_success(api.send_draft(pipeline["draft_id"], IR_ANALYST))
    assert sent["status"] == "SENT"

    answered = validate_success(api.get_inquiry(pipeline["inquiry_id"], IR_ANALYST))
    assert answered["status"] == "ANSWERED"
    assertions.assert_ts_equals(
        answered["answered_at"], "2026-08-12T00:00:00.000Z", "answered_at"
    )

    recounted = validate_success(api.get_company(company["id"], IR_ADMIN))
    assert recounted["open_inquiry_count"] == 0
    assert recounted["version"] == before["version"] + 1
    assertions.assert_open_inquiry_count(recounted, [answered])


def test_recompute_after_the_clock_move_lands_on_blackout_and_stops_the_next_send(
    api: ApiClient,
):
    """PRD §2.7: "The first is the issuer's scheduled earnings quiet period, delimited by `blackout_window_start` and `blackout_window_end`; the issuer is inside that window when a start instant has been configured, that start instant is at or before the logical clock, and the logical clock is strictly before the end instant."
    PRD §2.7: "If the issuer is inside its blackout window, or if any flagged activist of that issuer carries threat level `CRITICAL`, the posture is `BLACKOUT`."
    PRD §3.1: "The refresh re-derives `disclosure_posture` and recounts `open_inquiry_count`, stamps `posture_recomputed_at` with the logical clock, and increments the issuer's `version` by 1."
    PRD §3.1: "When the refresh lands on `BLACKOUT`, it does not stop at the issuer row: every response draft of that issuer sitting in `IN_REVIEW` whose `disclosure_class` is `MATERIAL_NONPUBLIC` is forced to `BLOCKED` with `blocked_reason` set to `POSTURE_BLACKOUT`, and each of those drafts' inquiry tickets is rewound from `AWAITING_APPROVAL` to `DRAFTING` with a freshly computed `sla_due_at`."
    PRD §3.6: "It is refused with `ERR_DRAFT_INVALID_STATE` on a draft that is not `APPROVED`, with `ERR_DRAFT_AUTHOR_MISMATCH` when anyone but the author attempts it, and with `ERR_DISCLOSURE_BLACKOUT` when the issuer's stored `disclosure_posture` is `BLACKOUT` — an answer approved before the quiet period began still cannot leave the building during it."

    Design: Corner/consistency_model/writes_and_their_cascades_are_visible_immediately
    """
    company, _holder, pipeline = _approved_public_answer(api)

    before = validate_success(api.get_company(company["id"], IR_ADMIN))
    draft_before = validate_success(
        api.get_response_draft(pipeline["draft_id"], IR_ANALYST)
    )

    fixtures.set_clock(api, CLOCK_INSIDE_BLACKOUT)

    refreshed = validate_success(
        api.recompute_posture(company["id"], DISCLOSURE_OFFICER)
    )
    assert refreshed["disclosure_posture"] == "BLACKOUT"
    assert refreshed["version"] == before["version"] + 1
    assert refreshed["open_inquiry_count"] == 1
    assertions.assert_ts_equals(
        refreshed["posture_recomputed_at"],
        "2026-08-12T00:00:00.000Z",
        "posture_recomputed_at",
    )

    draft_after = validate_success(
        api.get_response_draft(pipeline["draft_id"], IR_ANALYST)
    )
    assert draft_after["status"] == "APPROVED"
    assert draft_after["blocked_reason"] is None
    assert draft_after["version"] == draft_before["version"]

    validate_error(
        api.send_draft(pipeline["draft_id"], IR_ANALYST),
        ApiErrorId.DISCLOSURE_BLACKOUT.value,
    )

    still_awaiting = validate_success(
        api.get_inquiry(pipeline["inquiry_id"], IR_ANALYST)
    )
    assert still_awaiting["status"] == "AWAITING_APPROVAL"
    assert still_awaiting["answered_at"] is None
