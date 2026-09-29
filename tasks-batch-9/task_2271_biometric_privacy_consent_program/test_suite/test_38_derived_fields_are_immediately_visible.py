"""Read-your-writes, with no second call needed to see a computed field.

Everything activation derives is already in the activation response, and the program
read that immediately follows is already recomputed.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    assert_instant_equals,
    assert_program_state,
    compliance_baseline,
    create_asset,
    read_program,
    set_clock,
    validate_success,
)


def test_activation_reports_its_own_derived_fields_and_the_next_read_is_already_current(api):
    """The pinned policy, the stamped start and the horizon arrive in one response.

    PRD §3.5: "Activation then pins `pinned_policy_id` to that single published in-scope
    policy, stamps `collection_started_at` from the current logical clock **only when it
    is currently null** — that is, on the very first activation and never again —
    computes `destruction_due_at`, and recomputes the program's `consent_gap_count`, its
    inventory completeness and its `posture`."

    PRD §3.5: "First, the **effective retention** in days is the smaller of the pinned
    policy's `retention_days` and the state profile's `retention_max_days` — a policy may
    promise a shorter life than the statute allows but never a longer one. The **schedule
    horizon** is `collection_started_at` plus that many whole days."

    PRD §2.9: "One read is deliberately a read-through: reading a single compliance program
    recomputes `inventory_completeness_pct` and `posture` from current child state before
    responding, but does **not** refresh `updated_at` and does **not** increment the
    program's `version`."

    No second read of the collection point is issued: the assertions about the pin, the
    start instant and the thirty-day horizon are made against the transition response
    itself. The program read that follows immediately afterwards already reflects the
    activation, with no polling and no intervening call.

    Design: Corner/consistency_model/computed_fields_are_visible_in_the_same_response_that_changed_them
    """
    ctx = compliance_baseline(api)
    point = create_asset(
        api, ctx["program_id"], ctx["jurisdiction_id"], target_status="CLASSIFIED"
    )
    set_clock(api, "2026-08-15T00:00:00Z")

    activated = validate_success(
        api.transition_asset(point["id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )

    assert activated["status"] == "ACTIVE"
    assert activated["pinned_policy_id"] == ctx["policy_id"]
    assert_instant_equals(
        activated["collection_started_at"], "2026-08-15T00:00:00.000Z", "collection_started_at"
    )
    assert_instant_equals(
        activated["destruction_due_at"], "2026-09-14T00:00:00.000Z", "destruction_due_at"
    )

    assert_program_state(
        read_program(api, ctx["program_id"]),
        inventory_completeness_pct=100.00,
        posture="OPEN",
        consent_gap_count=0,
        gated_asset_count=0,
    )
