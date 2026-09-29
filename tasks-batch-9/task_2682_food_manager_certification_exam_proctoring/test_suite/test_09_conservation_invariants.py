"""Two conserved quantities and their compensating pairs: access-code inventory
across assign/cancel, and the provider ledger across issuance/revocation."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assert_inventory_conservation,
    assign_code,
    factories as f,
    get_success_data,
    purchase_batch,
    resolve_incident,
    schedule_session,
    setup_landscape,
    setup_sitting,
    take_incident_into_review,
    file_incident,
    validate_success,
)

_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]
_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]


def _depleted_two_unit_batch(api):
    env = setup_landscape()
    cand_a = add_candidate(env)
    cand_b = add_candidate(env)
    cand_c = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    code_a, batch = assign_code(env, batch, cand_a)
    code_b, batch = assign_code(env, batch, cand_b)
    session = schedule_session(env, cand_a, code_a, "2026-09-10T09:00:00Z",
                              proctor=proctor)
    env.update({"cand_a": cand_a, "cand_b": cand_b, "cand_c": cand_c,
                "proctor": proctor, "batch": batch, "code_a": code_a,
                "code_b": code_b, "session": session})
    return env


def test_cancellation_returns_the_inventory_counters_to_their_pre_assignment_values(api):
    """The cancellation compensates the assignment exactly, and the partition
    still sums to quantity_purchased at both ends.

    PRD: "For every batch, `available_count` plus `assigned_count` plus
    `consumed_count` plus `voided_count` always equals `quantity_purchased`, after
    every request; `voided_count` counts both `VOIDED` and `EXPIRED` codes, so
    nothing ever falls out of the partition."

    PRD: "`available_count` and `assigned_count` return to their pre-assignment
    values and the only residue is the code's `assignment_release_count`, which
    counts how many times that code has returned from `ASSIGNED` to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/assign_then_cancel_restores_access_code_inventory_conservation_with_release_residue
    """
    env = _depleted_two_unit_batch(api)
    admin = env["admin_headers"]
    before = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))
    assert (before["available_count"], before["assigned_count"]) == (0, 2)
    assert (before["consumed_count"], before["voided_count"]) == (0, 0)
    assert before["status"] == "DEPLETED"
    assert_inventory_conservation(before)

    cancelled = get_success_data(api.cancel_exam_session(
        env["session"]["id"], f.create_cancellation_payload(
            reason="Candidate withdrew from the 10 September sitting"),
        env["provider_headers"]))
    assert (cancelled["session_status"], cancelled["proctoring_status"]) == (
        "CANCELLED", "CLEARED")

    after = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))
    assert (after["available_count"], after["assigned_count"]) == (1, 1)
    assert (after["consumed_count"], after["voided_count"]) == (0, 0)
    assert after["status"] == "ACTIVE"
    assert after["version"] > before["version"]
    assert_inventory_conservation(after)

    code = get_success_data(api.get_access_code(env["code_a"]["id"],
                                                env["provider_headers"]))
    assert code["status"] == "AVAILABLE"
    assert code["candidate_id"] is None
    assert code["assigned_at"] is None
    assert code["assignment_release_count"] == 1

    # No money moved in either direction, and the held capacity came back.
    assert after["total_price_cents"] == 7524
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 492476
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 0
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 0


def test_the_release_residue_survives_a_reassignment_of_the_freed_unit(api):
    """Handing the freed unit to a third candidate re-depletes the batch and
    leaves the release counter where it was.

    PRD: "the only residue is the code's `assignment_release_count`, which counts
    how many times that code has returned from `ASSIGNED` to `AVAILABLE`"

    Design: Difficulty/compensating_invariant/assign_then_cancel_restores_access_code_inventory_conservation_with_release_residue
    """
    env = _depleted_two_unit_batch(api)
    validate_success(api.cancel_exam_session(
        env["session"]["id"], f.create_cancellation_payload(),
        env["provider_headers"]))
    reopened = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))

    code_c, refreshed = assign_code(env, reopened, env["cand_c"])

    assert code_c["id"] == env["code_a"]["id"]
    assert code_c["candidate_id"] == env["cand_c"]["id"]
    assert code_c["assignment_release_count"] == 1
    assert (refreshed["available_count"], refreshed["assigned_count"]) == (0, 2)
    assert refreshed["status"] == "DEPLETED"
    assert_inventory_conservation(refreshed)


def test_certificate_issuance_debits_only_the_charged_counter(api):
    """The fee is a debit: charged grows by 1500, credited does not move, and the
    balance identity holds after the posting.

    PRD: "`credit_balance_cents` is always exactly `lifetime_credited_cents` minus
    `lifetime_charged_cents`. That identity is an invariant that must hold after
    every single request."

    PRD: "`issuance_fee_cents` is set to 1,500 cents and that same amount is added
    to the `lifetime_charged_cents` of the provider named by the candidate's
    `training_provider_id`, with `credit_balance_cents` recomputed."

    Design: Difficulty/compensating_invariant/certificate_issuance_then_revocation_restores_ledger_identity_while_both_counters_grow
    """
    env = setup_sitting(stage="CLOSED", scored_correct_count=60,
                        scoring_admin_headers=_SCORING_ADMIN)
    admin = env["admin_headers"]
    before = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert before["lifetime_credited_cents"] == 500000
    assert before["lifetime_charged_cents"] == 3762
    assert before["credit_balance_cents"] == 496238
    assert (before["lifetime_credited_cents"] - before["lifetime_charged_cents"]
            == before["credit_balance_cents"])

    certificate = get_success_data(api.create_certificate(
        f.create_certificate_payload(env["score_report"]["id"]), admin), 201)

    assert certificate["issuance_fee_cents"] == 1500
    assert certificate["status"] == "ISSUED"
    after = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert after["lifetime_charged_cents"] == 5262
    assert after["lifetime_credited_cents"] == 500000
    assert after["credit_balance_cents"] == 494738
    assert (after["lifetime_credited_cents"] - after["lifetime_charged_cents"]
            == after["credit_balance_cents"])


def test_revocation_restores_the_balance_while_both_counters_keep_growing(api):
    """The compensating credit returns the balance bit-for-bit to its pre-issuance
    value, and the debit is never unwound.

    PRD: "Certificate issuance debits a fixed fee of 1500 cents (fifteen dollars)
    and, if that certificate is later revoked, exactly the same 1500 cents is
    credited back."

    PRD: "`credit_balance_cents` therefore returns to its pre-issuance value with
    zero drift, while both lifetime counters have each grown by 1500 cents — the
    audit trail keeps both postings."

    Design: Difficulty/compensating_invariant/certificate_issuance_then_revocation_restores_ledger_identity_while_both_counters_grow
    """
    env = setup_sitting(stage="CERTIFIED", scored_correct_count=60,
                        scoring_admin_headers=_SCORING_ADMIN)
    admin = env["admin_headers"]
    issued = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert issued["credit_balance_cents"] == 494738

    incident = file_incident(env, env["session"], env["proctor"], severity="MAJOR")
    assert incident["severity_weight"] == 3
    incident = take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    resolved = resolve_incident(env, incident, outcome="SUBSTANTIATE",
                               admin_headers=_SECURITY_ADMIN)
    assert resolved["status"] == "SUBSTANTIATED"

    final = get_success_data(api.get_training_provider(env["provider"]["id"], admin))
    assert final["lifetime_credited_cents"] == 501500
    assert final["lifetime_charged_cents"] == 5262
    assert final["credit_balance_cents"] == 496238
    assert (final["lifetime_credited_cents"] - final["lifetime_charged_cents"]
            == final["credit_balance_cents"])

    certificate = get_success_data(api.get_certificate(env["certificate"]["id"], admin))
    assert certificate["status"] == "REVOKED"
    assert certificate["revocation_reason"] == "SCORE_VOIDED"
