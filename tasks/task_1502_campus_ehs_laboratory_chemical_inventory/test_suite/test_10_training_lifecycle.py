"""Training assignment lifecycle: clock-sweep expiry and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_worker,
    create_lab,
    create_training_payload,
    get_lab,
    make_pi_headers,
    set_clock,
    validate_error,
    validate_success,
    get_success_data,
)

ADMIN = TEST_USERS["admin_headers"]


def test_training_assignment_expires_on_clock_sweep(api):
    """PRD §2.5: "every training assignment still `ASSIGNED` whose `due_date` is
    strictly earlier than the new logical now transitions to `EXPIRED`"
    PRD §2.6: "Otherwise, if at least one training assignment of the lab is in
    `EXPIRED` status, posture is `RESTRICTED`."

    Design: Corner/state_machines/training_assignment_expires_on_clock_sweep
    """
    lab = create_lab(name="Lab H", department="Biology", building="Hall B", room="203")
    pi = add_worker(lab["id"], full_name="Dr. Py", role_in_lab="PI")
    assignment = get_success_data(
        api.create_training_assignment(
            create_training_payload(
                lab["id"], pi["id"], hazard_class="TOXIC",
                due_date="2026-08-10T00:00:00Z",
            ),
            ADMIN,
        )
    )
    assert assignment["status"] == "ASSIGNED"

    # at exactly the due_date: not strictly earlier, so no expiry
    set_clock("2026-08-10T00:00:00Z")
    data = get_success_data(api.list_worker_training_assignments(pi["id"], ADMIN))
    assert data[0]["status"] == "ASSIGNED", (
        "due_date == logical now does not expire (strict inequality)"
    )

    # past the due_date: the sweep expires it
    set_clock("2026-08-11T00:00:00Z")
    data = get_success_data(api.list_worker_training_assignments(pi["id"], ADMIN))
    assert data[0]["status"] == "EXPIRED"
    assert get_lab(lab["id"])["posture"] == "RESTRICTED", (
        "an EXPIRED assignment drives posture RESTRICTED via the expired-training rule"
    )


def test_complete_expired_training_rejected(api):
    """PRD §3.1: "Completing an assignment that is no longer `ASSIGNED` is rejected
    with `ERR_TRAINING_STATE` (HTTP 409)."
    PRD §2.5: "every training assignment still `ASSIGNED` whose `due_date` is
    strictly earlier than the new logical now transitions to `EXPIRED`"

    Design: Corner/validations/complete_expired_training_rejected
    """
    lab = create_lab(name="Lab W2", department="Biology", building="Hall B", room="209")
    pi = add_worker(lab["id"], full_name="Dr. Py", role_in_lab="PI")
    assignment = get_success_data(
        api.create_training_assignment(
            create_training_payload(
                lab["id"], pi["id"], hazard_class="TOXIC",
                due_date="2026-08-05T00:00:00Z",
            ),
            ADMIN,
        )
    )
    set_clock("2026-08-06T00:00:00Z")

    data = get_success_data(api.list_worker_training_assignments(pi["id"], ADMIN))
    assert data[0]["status"] == "EXPIRED"

    res = api.complete_training_assignment(assignment["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_TRAINING_STATE)

    data = get_success_data(api.list_worker_training_assignments(pi["id"], ADMIN))
    assert data[0]["status"] == "EXPIRED", "rejected completion leaves status EXPIRED"
