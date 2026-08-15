"""Term lifecycle, calendar gates, and rate-card window claims (PRD §3.1, §3.10)."""
from test_helpers import (
    ApiErrorId,
    assert_millis_timestamp,
    create_draft_term,
    create_open_term,
    create_term_payload,
    create_tuition_rate_payload,
    enroll,
    is_valid_uuid,
    make_student,
    set_clock,
    validate_error,
    validate_success,
)


def test_term_create_defaults(api, registrar_headers):
    """PRD §3.1: "A term is born in `DRAFT` status."
    PRD §2.9: "an `id` that is a server-generated UUID with no type prefix; a
    `created_at` ISO 8601 UTC timestamp with three fractional digits".

    Design: Corner/entities/term_create_defaults
    """
    res = api.create_term(create_term_payload(), registrar_headers)
    term = validate_success(res, 201)
    assert term["status"] == "DRAFT", "a newly created term must be DRAFT"
    assert is_valid_uuid(term["id"]), "id must be a server-minted UUID"
    assert_millis_timestamp(term["created_at"], "created_at")
    assert_millis_timestamp(term["updated_at"], "updated_at")
    # Client input must not leak into the system-managed status field.
    assert term["code"] == "FALL-26"


def test_lock_census_from_draft_rejected(api, registrar_headers):
    """PRD §3.1: "attempting the lock before the census date, or from any state
    other than `OPEN`, likewise fails with `ERR_TERM_STATE_INVALID`."

    Design: Corner/state_machines/term_lock_census_from_draft_rejected
    """
    term = create_draft_term()
    res = api.transition_term(term["id"], {"action": "LOCK_CENSUS"}, registrar_headers)
    validate_error(res, ApiErrorId.ERR_TERM_STATE_INVALID, expected_status=409)
    after = validate_success(api.get_term(term["id"], registrar_headers), 200)
    assert after["status"] == "DRAFT", "rejected transition must leave the term DRAFT"


def test_term_lifecycle_gate_errors(api, registrar_headers, bursar_manager_headers):
    """PRD §3.2: "Enrollment requires the term to be `OPEN` — any other term
    state yields `ERR_TERM_NOT_OPEN` (HTTP 409)".
    PRD §3.10: "close is refused while any account of the term still holds a
    positive balance in a non-`WRITTEN_OFF` state — that rejection is
    `ERR_TERM_NOT_CLOSABLE` (HTTP 409)."

    Design: Corner/errors/term_lifecycle_gate_errors
    """
    term = create_draft_term()
    rate_res = api.create_tuition_rate(
        create_tuition_rate_payload(term_id=term["id"]), registrar_headers
    )
    validate_success(rate_res, 201)
    student = make_student("S-GTE", "Gate")

    # Enrollment while the term is still DRAFT is gated by term state.
    res = api.create_enrollment(
        {
            "student_id": student["id"],
            "term_id": term["id"],
            "credit_hours": 1,
            "effective_date": "2026-08-25",
        },
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_TERM_NOT_OPEN, expected_status=409)

    opened = validate_success(
        api.transition_term(term["id"], {"action": "OPEN"}, registrar_headers), 200
    )
    assert opened["status"] == "OPEN"
    enroll(student["id"], term["id"], credit_hours=1)

    # LOCK_CENSUS allowed once the clock has reached census_date (2026-09-07).
    set_clock("2026-09-08T00:00:00Z")
    locked = validate_success(
        api.transition_term(term["id"], {"action": "LOCK_CENSUS"}, registrar_headers),
        200,
    )
    assert locked["status"] == "CENSUS_LOCKED"

    # CLOSE refused: the account still owes the 50000-cent assessment.
    res = api.transition_term(term["id"], {"action": "CLOSE"}, bursar_manager_headers)
    validate_error(res, ApiErrorId.ERR_TERM_NOT_CLOSABLE, expected_status=409)


def test_registrar_cannot_close_term(api, registrar_headers):
    """PRD §3.1: "The final transition, `action` set to `CLOSE`, is reserved for
    a `BursarManager`".
    PRD §2.1: "A request whose role is recognized but not permitted on the
    targeted endpoint — or whose entity-backed ownership check fails — is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/registrar_cannot_close_term
    """
    term = create_draft_term()
    res = api.transition_term(term["id"], {"action": "CLOSE"}, registrar_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestRateWindowClosedInterval:
    """CLOSED effective-window overlap on rate cards (PRD §3.1)."""

    def test_touching_endpoints_overlap(self, api, registrar_headers):
        """PRD §3.1: "two rate cards for the same term, residency, and level
        may not have overlapping windows, where merely touching endpoints
        already count as overlap; a collision is rejected with
        `ERR_RATE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/tuition_rate_closed_interval_touch
        """
        term = create_open_term()
        first = validate_success(
            api.create_tuition_rate(
                create_tuition_rate_payload(term_id=term["id"]), registrar_headers
            ),
            201,
        )
        assert first["effective_to"] == "2026-12-31"
        # A second card whose effective_from equals the first card's
        # effective_to shares that date under CLOSED semantics.
        res = api.create_tuition_rate(
            create_tuition_rate_payload(
                term_id=term["id"],
                per_credit_rate_cents=36000,
                flat_rate_cents=432000,
                overload_rate_cents=36000,
                effective_from="2026-12-31",
                effective_to="2027-05-31",
            ),
            registrar_headers,
        )
        validate_error(res, ApiErrorId.ERR_RATE_WINDOW_OVERLAP, expected_status=409)

    def test_one_day_gap_between_windows_allowed(self, api, registrar_headers):
        """PRD §3.1: "Each rate card governs a **closed** effective window from
        `effective_from` through `effective_to` inclusive — the end must not
        precede the start — and two rate cards for the same term, residency,
        and level may not have overlapping windows, where merely touching
        endpoints already count as overlap".

        Design: Difficulty/resource_temporal_overlap/tuition_rate_closed_interval_touch
        """
        term = create_open_term()
        validate_success(
            api.create_tuition_rate(
                create_tuition_rate_payload(term_id=term["id"]), registrar_headers
            ),
            201,
        )
        # Starting the day AFTER the existing window closes leaves no shared
        # date, so the new card must be accepted.
        created = validate_success(
            api.create_tuition_rate(
                create_tuition_rate_payload(
                    term_id=term["id"],
                    per_credit_rate_cents=36000,
                    flat_rate_cents=432000,
                    overload_rate_cents=36000,
                    effective_from="2027-01-01",
                    effective_to="2027-05-31",
                ),
                registrar_headers,
            ),
            201,
        )
        assert created["effective_from"] == "2027-01-01"
        assert created["term_id"] == term["id"]
