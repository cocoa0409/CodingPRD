"""Immediate consistency: a cascade is already visible in the response that caused it.

Every test drives real HTTP against a live server whose database is empty and whose
logical clock reads 2026-08-01T00:00:00Z; the clock only ever moves forward.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures as fx


def test_immediate_consistency_cascade_visible_in_same_response(api, aide, therapist):
    """Closing documentation returns a body that already reflects the whole cascade.

    A one-hour session with two enrolled residents is documented — one LEADING, one
    ACTIVE — and then closed. The close response itself already reports the session as
    DOCUMENTED with its documentation stamp and roster count, an immediately following
    re-read of the same session returns exactly the same body, both participation rows
    are already FINALIZED, and each resident's engagement index already holds its
    post-cascade value. Nothing lags behind the response and nothing needs a retry.

    PRD: "By the time a response is returned, every dependent state change and every
    dependent recomputation the operation implies has already been applied and is
    observable on the affected resources."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_response
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    ida, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Immediate Ida",
            "room_number": "715A",
            "admission_date": "2026-08-01",
        },
        preferred_group_size="LARGE",
        effective_date="2026-08-01",
    )
    ivan, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Immediate Ivan",
            "room_number": "715B",
            "admission_date": "2026-08-01",
        },
        preferred_group_size="LARGE",
        effective_date="2026-08-01",
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Immediate Read Program",
            "domain": "SOCIAL",
            "staffing_ratio_denominator": 4,
            "max_group_size": 10,
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Immediate Read Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-05T14:00:00Z",
        ends_at="2026-08-05T15:00:00Z",
        assigned_staff_count=4,
    )
    record_ida = fx.enroll(api, session["id"], ida["id"])
    record_ivan = fx.enroll(api, session["id"], ivan["id"])

    fx.advance_clock(api, "2026-08-05T14:00:00Z")
    fx.start_session(api, session["id"])
    fx.document_attendance(api, record_ida["id"], engagement_level="LEADING")
    fx.document_attendance(api, record_ivan["id"], engagement_level="ACTIVE")

    closed = validate_success(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide), 200
    )
    assert closed["status"] == "DOCUMENTED", (
        f"The closing response must already report the new state, got {closed['status']!r}"
    )
    assert closed["documented_at"] == "2026-08-05T14:00:00.000Z", (
        f"The documentation stamp is the clock reading, got {closed['documented_at']!r}"
    )
    assert closed["enrolled_count"] == 2, (
        f"Both roster rows are still counted, got {closed['enrolled_count']}"
    )

    reread = get_success_data(api.get_session(session["id"], aide))
    assert reread == closed, (
        "An immediate re-read must be identical to the body the close already returned; "
        f"close returned {closed!r} and the re-read returned {reread!r}"
    )

    assert fx.read_record(api, record_ida["id"], aide)["status"] == "FINALIZED"
    assert fx.read_record(api, record_ivan["id"], aide)["status"] == "FINALIZED"

    assert fx.read_resident(api, ida["id"], therapist)["engagement_index"] == 1.0, (
        "A single LEADING attendance scores 4 of a possible 4"
    )
    assert fx.read_resident(api, ivan["id"], therapist)["engagement_index"] == 0.75, (
        "A single ACTIVE attendance scores 3 of a possible 4"
    )
