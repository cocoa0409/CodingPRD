"""Creation defaults, append-only snapshot shape, and the referral lazy-expiry
boundary (PRD §3.3, §3.6, §2.5, §3.8, §2.4)."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    assert_outcome_snapshot,
    create_certified_coach,
    create_participant,
    create_referral_for,
    set_clock,
    validate_error,
    validate_success,
)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime (format-agnostic:
    PRD pins the *instant* expires_at lands on, not its fractional-digit
    serialization)."""
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t).astimezone(timezone.utc)


def test_participant_create_applies_defaults(api, admin_headers):
    """PRD §3.3: "New participants begin `ACTIVE` with `no_show_count` at 0."

    Design: Corner/entities/participant_create_applies_defaults
    """
    participant = validate_success(
        api.create_participant(
            {"full_name": "D One", "email": "d1@test.org",
             "annual_income_cents": 1500000},
            admin_headers,
        ),
        expected_status=201,
    )
    assert participant["status"] == "ACTIVE"
    assert participant["no_show_count"] == 0


def test_outcome_snapshot_immutable_common_fields_absent(api, admin_headers):
    """PRD §2.5: "An outcome snapshot is an append-only event log entry and
    carries only `id` and `created_at`; both `updated_at` and `version` are
    absent."

    Design: Corner/entities/outcome_snapshot_immutable_common_fields_absent
    """
    participant = create_participant(admin_headers, full_name="Snap P",
                                     email="snap@test.org")
    snapshot = validate_success(
        api.create_outcome_snapshot(
            {"participant_id": participant["id"],
             "recorded_at": "2026-08-01T00:00:00Z", "credit_score": 640},
            admin_headers,
        ),
        expected_status=201,
    )
    # assert_outcome_snapshot enforces: id + created_at present; updated_at and
    # version absent (append-only shape).
    assert_outcome_snapshot(snapshot)
    assert "id" in snapshot and "created_at" in snapshot


def test_referral_lazy_expiry_at_exactly_30_days(api, admin_headers):
    """PRD §3.8: "The referral is born `SENT`, with `sent_at` stamped from the
    logical clock and `expires_at` computed as exactly 30 days after
    `sent_at`." PRD §2.4: "a `SENT` referral whose `expires_at` has been
    reached or passed is transitioned to `EXPIRED` the next time that referral
    is read or written." PRD §3.8: "an unreachable target — including any move
    out of an already-terminal referral — is rejected with
    `ERR_INVALID_TRANSITION`."

    Design: Corner/state_machines/referral_lazy_expiry_at_exactly_30_days
    """
    coach = create_certified_coach(admin_headers, full_name="CRE", email="cre@test.org")
    participant = create_participant(admin_headers, full_name="PRE", email="pre@test.org")
    referral = create_referral_for(participant["id"], coach["id"], admin_headers,
                                   partner_name="CommBank", partner_type="LENDER")
    assert referral["status"] == "SENT"
    # PRD §3.8: expires_at is exactly 30 days after sent_at. Compare the parsed
    # instants (PRD pins the instant, not the fractional-digit string format).
    sent = _parse_iso(referral["sent_at"])
    expires = _parse_iso(referral["expires_at"])
    assert expires == sent + timedelta(days=30)
    # The referral was created at the default clock 2026-08-01T00:00:00Z.
    assert sent == datetime(2026, 8, 1, tzinfo=timezone.utc)

    # Read at exactly expires_at: the >= boundary sweeps it to EXPIRED.
    set_clock("2026-08-31T00:00:00Z", admin_headers)
    swept = validate_success(api.get_referral(referral["id"], admin_headers))
    assert swept["status"] == "EXPIRED"

    # EXPIRED is terminal: a later ACCEPTED transition is unreachable.
    resp = api.transition_referral(
        referral["id"], {"target_state": "ACCEPTED"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
