"""Lab closeout/decommission lifecycle: cleanliness gate and terminal posture."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_container_payload,
    create_lab_with_pi,
    get_lab,
    make_pi_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_decommission_blocked_by_remaining_containers(api):
    """PRD §3.8: "It is permitted only when the lab's books are clean across five
    dimensions: no container of the lab in any state other than `PICKED_UP`; no
    pickup request in `DRAFT`, `SUBMITTED`, `REJECTED`, or `SCHEDULED`; no corrective
    action in `OPEN`, `SUBMITTED`, or `REOPENED`; no registration in `PENDING`,
    `ACTIVE`, or `SUSPENDED` (surrender is therefore a prerequisite for any regulated
    lab); and no incident in `REPORTED` status." and "any violation of the five
    cleanliness checks is rejected with `ERR_DECOMMISSION_BLOCKED` (HTTP 409)."

    Design: Corner/validations/decommission_blocked_by_remaining_containers
    """
    lab, pi = create_lab_with_pi(name="Lab U2", room="116")
    validate_success(
        api.create_container(
            create_container_payload(lab["id"], barcode="DB-1", quantity_value=1.0),
            make_pi_headers(pi["id"]),
        ),
        201,
    )
    validate_success(api.closeout_lab(lab["id"], make_pi_headers(pi["id"])), 200)

    res = api.decommission_lab(lab["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_DECOMMISSION_BLOCKED)
    assert get_lab(lab["id"])["status"] == "CLOSING", "rejected decommission leaves status CLOSING"


def test_decommission_succeeds_when_books_clean(api):
    """PRD §3.8: "Decommissioning finalizes the lab from `CLOSING` to the terminal
    `DECOMMISSIONED` status and is an `EHSAdmin`-only action." and "On success the
    lab's `posture` is set to `FROZEN` — consistent with derivation rule 1 — and the
    lab's `version` increments by 1."
    PRD §2.6: "If the lab's `status` is `DECOMMISSIONED`, posture is `FROZEN`."

    Design: Corner/validations/decommission_succeeds_when_clean
    """
    lab, pi = create_lab_with_pi(name="Lab V2", room="117")
    closed = validate_success(api.closeout_lab(lab["id"], make_pi_headers(pi["id"])), 200)
    assert closed["status"] == "CLOSING"

    decommissioned = validate_success(api.decommission_lab(lab["id"], ADMIN), 200)
    assert decommissioned["status"] == "DECOMMISSIONED"
    assert decommissioned["posture"] == "FROZEN", (
        "decommission sets posture FROZEN (derivation rule 1)"
    )
    assert decommissioned["version"] == closed["version"] + 1


def test_container_create_in_closing_lab_rejected(api):
    """PRD §3.2: "Registration is refused with `ERR_INVALID_REQUEST` (HTTP 400) when
    the quantity is not greater than zero; with `ERR_LAB_STATE` (HTTP 409) when the
    lab's `status` is not `ACTIVE`; with `ERR_LAB_FROZEN` when the lab's posture is
    `FROZEN`; and with `ERR_DUPLICATE_BARCODE` (HTTP 409) when the barcode already
    exists within the lab."

    Design: Corner/validations/container_create_in_closing_lab_rejected
    """
    lab, pi = create_lab_with_pi(name="Lab Y2", room="118")
    validate_success(api.closeout_lab(lab["id"], make_pi_headers(pi["id"])), 200)
    assert get_lab(lab["id"])["status"] == "CLOSING"

    res = api.create_container(
        create_container_payload(lab["id"], barcode="CL-1", quantity_value=1.0),
        make_pi_headers(pi["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LAB_STATE)
