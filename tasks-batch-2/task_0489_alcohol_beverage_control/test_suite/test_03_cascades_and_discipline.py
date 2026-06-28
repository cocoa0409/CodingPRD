"""Cascading side effects and conserved-quantity invariants: the violation-sustain
suspension cascade, the hearing-sustain quota release, the quota and fine-ledger
conservation pairs, and immediate (same-request) consistency.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_applicant_headers,
    make_examiner_headers,
    setup_issued_license,
    setup_license_with_active_permit,
    create_submitted_application,
    setup_application_in_protest_hearing,
    create_server_permit,
    activate_server_permit,
    file_violation,
    sustain_violation,
    get_quota_status,
)

DIRECTOR = TEST_USERS["director_headers"]
ADJUDICATOR = TEST_USERS["adjudication_officer_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────────
def test_violation_sustain_cascade_suspends_license_and_expires_permits(api):
    """PRD §3.9: "if the license's `demerit_points` has reached ten or more, the
    suspension threshold fires: an `ACTIVE` or `RENEWAL_DUE` license is suspended
    and its attached `ACTIVE` server permits are expired with `active_server_count`
    driven to zero."
    PRD §3.9: "an `EGREGIOUS` adds six" and "a `SERIOUS` adds four"

    Prior EGREGIOUS sustained (demerit 6) + one ACTIVE permit; a SERIOUS sustain
    adds 4 -> 10, suspending the license (depth: action+demerits -> suspension ->
    permit EXPIRED -> active_server_count 0).

    Design: Difficulty/transitive_cascade/violation_sustain_cascade_depth_four_to_server_permit_expiry
    """
    bundle = setup_license_with_active_permit()
    lic_id = bundle["license"]["id"]
    permit_id = bundle["permit"]["id"]
    # Prior EGREGIOUS (demerit 6).
    v1 = file_violation(lic_id, severity="EGREGIOUS")
    sustain_violation(v1["id"], action_type="FINE")
    # Trigger: SERIOUS adds 4 -> demerit 10 -> suspension cascade.
    v2 = file_violation(lic_id, severity="SERIOUS")
    sustained = validate_success(api.sustain_violation(
        v2["id"], {"action_type": "FINE"}, ADJUDICATOR))
    assert sustained["status"] == "SUSTAINED"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["demerit_points"] == 10, f"expected 10, got {lic['demerit_points']}"
    assert lic["status"] == "SUSPENDED", f"expected SUSPENDED, got {lic['status']}"
    assert lic["active_server_count"] == 0, f"expected 0, got {lic['active_server_count']}"
    permit = get_success_data(api.get_server_permit(permit_id, DIRECTOR))
    assert permit["status"] == "EXPIRED", f"expected EXPIRED, got {permit['status']}"


def test_hearing_sustain_cascade_denies_application_and_releases_quota(api):
    """PRD §3.5: "A `PROTEST_SUSTAINED` outcome moves the hearing to
    `PROTEST_SUSTAINED`, marks the protest `SUSTAINED`, denies the application
    (moving it to `DENIED`), and releases any reserved quota slot, freeing the
    region's count by one."

    Rendering PROTEST_SUSTAINED chains: hearing -> SUSTAINED, protest -> SUSTAINED,
    application -> DENIED, quota_slot_held -> false.

    Design: Difficulty/transitive_cascade/hearing_sustain_cascade_depth_three_to_quota_release
    """
    ref, app, protest, hearing_id = setup_application_in_protest_hearing(
        grounds="PUBLIC_NUISANCE", room_code="RM-1",
        starts_at="2026-01-10T09:00:00Z", ends_at="2026-01-10T11:00:00Z")
    get_success_data(api.set_clock("2026-01-10T12:00:00Z", DIRECTOR))
    rendered = validate_success(api.render_hearing(
        hearing_id, {"outcome": "PROTEST_SUSTAINED"}, ADJUDICATOR))
    assert rendered["outcome"] == "PROTEST_SUSTAINED"
    protest_after = get_success_data(api.get_protest(protest["id"], DIRECTOR))
    assert protest_after["status"] == "SUSTAINED", f"got {protest_after['status']}"
    app_after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert app_after["status"] == "DENIED", f"got {app_after['status']}"
    assert app_after["quota_slot_held"] is False, "quota slot released on DENIED"


# ─── Queue A: compensating_invariant ──────────────────────────────────────
def test_quota_reserve_then_withdraw_conserves_region_slots(api):
    """PRD §3.2: "For a quota-managed class it reserves a slot by setting
    `quota_slot_held` true and advancing the region's `version`, so that the
    availability count immediately reflects this application."
    PRD §3.2: "A `SUBMITTED` application may still be withdrawn; doing so releases
    the reserved quota slot (clearing `quota_slot_held`) if one was held."

    Submit reserves (available 2 -> 1); withdraw from SUBMITTED releases (1 -> 2),
    leaving available == cap == 2 and used 0.

    Design: Difficulty/compensating_invariant/quota_reserve_then_withdraw_conserves_region_slot_count
    """
    ref, app = create_submitted_application()
    owner = make_applicant_headers(ref["owner_id"])
    withdrawn = validate_success(api.withdraw_application(app["id"], owner))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["quota_slot_held"] is False
    status = get_quota_status(ref["region"]["id"], "ON_47")
    assert status["available"] == 2, f"expected available 2, got {status['available']}"
    assert status["used"] == 0, f"expected used 0, got {status['used']}"


def test_fine_charge_then_payment_conserves_outstanding_fine_ledger(api):
    """PRD §3.9: "Next it adds demerit points to the license's `demerit_points`
    and adds the new `fine_cents` to the license's `outstanding_fine_cents`,
    keeping the ledger in sync."
    PRD §3.9: "a fine payment supplies the `action_id` of the administrative
    action and an `amount_cents`, adding that amount to the action's
    `fine_paid_cents` and subtracting it from the license's `outstanding_fine_cents`,
    floored at zero."

    Sustain SERIOUS (fine 75000, outstanding 75000); full pay-fine 75000 restores
    outstanding to 0 with fine_paid_cents == fine_cents == 75000.

    Design: Difficulty/compensating_invariant/fine_charge_then_payment_conserves_outstanding_fine_ledger
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    vio = file_violation(lic_id, severity="SERIOUS")
    sustained = sustain_violation(vio["id"], action_type="FINE")
    action_id = sustained["action_id"]
    lic = validate_success(api.pay_fine(lic_id, {"action_id": action_id, "amount_cents": 75000}, owner))
    assert lic["outstanding_fine_cents"] == 0, (
        f"expected outstanding 0 after full payment, got {lic['outstanding_fine_cents']}"
    )
    action = get_success_data(api.get_administrative_action(action_id, DIRECTOR))
    assert action["fine_paid_cents"] == 75000, f"got {action['fine_paid_cents']}"
    assert action["fine_cents"] == 75000, f"got {action['fine_cents']}"


# ─── Queue B: state_machines / consistency_model ──────────────────────────
def test_background_fail_cascades_applicant_disqualified(api):
    """PRD §3.3: "When a check is resolved to `FAILED`, the system performs a
    cross-entity cascade: in addition to setting `result` to `FAILED` and stamping
    `resolved_at`, it sets the owning `Applicant`'s `disqualified` flag to true,
    bumping that applicant's `version` and `updated_at`."

    Design: Corner/state_machines/background_fail_cascades_applicant_disqualified
    """
    ref, app = create_submitted_application(applicant_overrides={"legal_name": "Risky Bar", "felony_flag": True})
    bc = get_success_data(api.list_application_background_checks(app["id"], TEST_USERS["examiner_headers"]))
    bc_id = bc[0]["id"]
    resolved = validate_success(api.resolve_background_check(
        bc_id, {"decision": "FAIL"}, make_examiner_headers("exam-1")))
    assert resolved["result"] == "FAILED", f"got {resolved['result']}"
    applicant = get_success_data(api.get_applicant(ref["owner_id"], DIRECTOR))
    assert applicant["disqualified"] is True, "owning applicant must be disqualified"


def test_server_permit_revoke_decrements_active_count(api):
    """PRD §3.7: "A `Director` may revoke an `ACTIVE` permit, moving it to
    `REVOKED` and decrementing the license's `active_server_count` by one."

    Design: Corner/state_machines/server_permit_revoke_decrements_active_count_bubble_up
    """
    bundle = setup_license_with_active_permit()
    lic_id = bundle["license"]["id"]
    permit_id = bundle["permit"]["id"]
    revoked = validate_success(api.revoke_server_permit(permit_id, DIRECTOR))
    assert revoked["status"] == "REVOKED", f"got {revoked['status']}"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["active_server_count"] == 0, f"expected 0, got {lic['active_server_count']}"


def test_sustain_minor_immediately_reflects_fine_on_license(api):
    """PRD §2.5: "the system applies every cascade **atomically within the
    triggering request** — there is no eventual consistency and no deferred
    reconciliation."
    PRD §3.9: "A severity base is selected — twenty-five thousand cents for
    `MINOR`" and "a `MINOR` violation adds two points"

    Right after sustaining a MINOR violation, a license read shows
    outstanding_fine_cents 25000 and demerit_points 2 — no eventual lag.

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_response
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    vio = file_violation(lic_id, severity="MINOR")
    sustained = validate_success(api.sustain_violation(vio["id"], {"action_type": "FINE"}, ADJUDICATOR))
    action = get_success_data(api.get_administrative_action(sustained["action_id"], DIRECTOR))
    assert action["fine_cents"] == 25000, f"got {action['fine_cents']}"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["outstanding_fine_cents"] == 25000, f"got {lic['outstanding_fine_cents']}"
    assert lic["demerit_points"] == 2, f"got {lic['demerit_points']}"
