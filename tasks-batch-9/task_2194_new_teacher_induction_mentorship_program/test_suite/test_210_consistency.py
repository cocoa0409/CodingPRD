"""Cascades are visible in the very response that triggers them, in both directions.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.assertions import (
    assert_four_decimals,
    assert_money_cents,
    assert_two_decimals,
)
from test_helpers.fixtures import (
    build_program,
    read_match,
    read_mentor,
    read_novice,
    set_clock,
)
from test_helpers.test_users import ADMIN, make_mentor_headers, make_site_lead_headers


class TestSynchronousCascadeVisibility:
    """Verification and its compensating void both settle inside one request."""

    def test_verification_and_void_expose_every_derived_field_in_the_same_response(
        self, api: InductionApiClient
    ):
        """No second read is needed: the mutating response already carries the new figures.

        The PRD forbids deferred reconciliation outright: "Cascades are always applied
        immediately and synchronously within the triggering request — there is no
        deferred reconciliation — and they are always applied in a fixed order so that
        capacity checks inside a cascade are reproducible." The void reverses the same
        set of figures: "*Hop one* resets the log's own `credited_minutes` and
        `stipend_cents` to zero while `void_reason` preserves the audit trail, and
        recomputes the match's `verified_minutes_total` and `accrued_stipend_cents`,
        the mentor's `verified_minutes_lifetime` and `stipend_accrued_cents`, the
        novice's `verified_contact_minutes`, and the novice's `readiness_index_live`."

        Design: Corner/consistency_model/verification_and_void_expose_every_derived_field_in_the_same_response
        """
        program = build_program(api)
        set_clock(api, "2026-08-05T12:00:00Z")
        log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    program["match_id"],
                    "2026-08-03T09:00:00Z",
                    120,
                    "ONE_ON_ONE",
                    description=(
                        "Two-hour one-on-one planning conference covering unit pacing "
                        "and formative assessment design"
                    ),
                ),
                make_mentor_headers(program["mentor_id"]),
            ),
            201,
        )
        assert log["credited_minutes"] == 0, (
            f"a submitted log has credited nothing yet, got {log['credited_minutes']}"
        )

        verified = validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload("VERIFY", note="Minutes confirmed against the coaching log"),
                make_site_lead_headers(program["site_id"]),
            )
        )
        assert verified["verification_status"] == "VERIFIED"
        assert verified["credited_minutes"] == 120, (
            "the one-on-one weight is full value and the daily ceiling is not reached, got "
            f"{verified['credited_minutes']}"
        )
        assert verified["rate_tier_at_verification"] == "EXACT", (
            f"the tier is pinned from the match, got {verified['rate_tier_at_verification']}"
        )
        assert_two_decimals(
            verified["cert_multiplier_at_verification"],
            1.00,
            "cert_multiplier_at_verification",
        )
        assert_money_cents(verified["stipend_cents"], 8400, "stipend_cents")
        assert verified["verified_at"] is not None, "verification stamps the clock"

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["verified_minutes_lifetime"] == 120
        assert_money_cents(mentor["stipend_accrued_cents"], 8400, "stipend_accrued_cents")

        match = read_match(api, program["match_id"])
        assert match["verified_minutes_total"] == 120
        assert_money_cents(match["accrued_stipend_cents"], 8400, "accrued_stipend_cents")

        readiness = validate_success(api.get_readiness(program["novice_id"], ADMIN))
        assert_two_decimals(readiness["readiness_index_live"], 9.00, "readiness_index_live")
        assert_four_decimals(readiness["contact_component"], 0.2000, "contact_component")
        assert_four_decimals(
            readiness["observation_component"], 0.0000, "observation_component"
        )
        assert_four_decimals(readiness["seminar_component"], 0.0000, "seminar_component")
        assert readiness["seminar_denominator"] == 1, (
            f"the denominator is floored at one, got {readiness['seminar_denominator']}"
        )
        assert readiness["meets_readiness_gate"] is False

        void_reason = "Log was filed against the wrong novice"
        voided = validate_success(
            api.void_contact_log(log["id"], f.void_payload(void_reason=void_reason), ADMIN)
        )
        assert voided["verification_status"] == "VOIDED"
        assert voided["credited_minutes"] == 0, (
            f"the unwind is in the void response itself, got {voided['credited_minutes']}"
        )
        assert_money_cents(voided["stipend_cents"], 0, "stipend_cents")
        assert voided["void_reason"] == void_reason, (
            f"the audit trail is preserved, got {voided['void_reason']}"
        )

        after_readiness = validate_success(api.get_readiness(program["novice_id"], ADMIN))
        assert_two_decimals(
            after_readiness["readiness_index_live"], 0.00, "readiness_index_live"
        )
        assert_four_decimals(
            after_readiness["contact_component"], 0.0000, "contact_component"
        )

        after_mentor = read_mentor(api, program["mentor_id"])
        assert after_mentor["verified_minutes_lifetime"] == 0, (
            f"every credited minute is reversed, got {after_mentor['verified_minutes_lifetime']}"
        )
        assert_money_cents(
            after_mentor["stipend_accrued_cents"], 0, "stipend_accrued_cents"
        )

        after_match = read_match(api, program["match_id"])
        assert after_match["verified_minutes_total"] == 0
        assert_money_cents(
            after_match["accrued_stipend_cents"], 0, "accrued_stipend_cents"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["verified_contact_minutes"] == 0, (
            f"and the novice's counter with them, got {novice['verified_contact_minutes']}"
        )
        assert novice["license_advancement_status"] == "NOT_ELIGIBLE"
