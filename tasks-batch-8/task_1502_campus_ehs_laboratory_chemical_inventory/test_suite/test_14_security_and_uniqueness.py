"""Authentication, role authorization, ownership scope, and uniqueness constraints."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_worker,
    create_area_payload,
    create_container_payload,
    create_lab,
    create_lab_with_pi,
    create_training_payload,
    get_lab,
    get_success_data,
    make_lab_member_headers,
    make_pi_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_request_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role that is not
    one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_missing_auth_headers_unauthenticated
    """
    lab = create_lab(name="Lab AU", room="122")
    res = api.get_lab(lab["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_lab_member_cannot_create_accumulation_area(api):
    """PRD §2.1: "Once authenticated, a request whose role is not in the endpoint's
    allowed set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"
    PRD §4: POST /ehs/accumulation-areas is authorized for EHSAdmin only.

    Design: Corner/errors/lab_member_cannot_create_area_forbidden
    """
    lab = create_lab(name="Lab RB", room="123")
    member = add_worker(lab["id"], full_name="Rita Res", role_in_lab="RESEARCHER")

    res = api.create_accumulation_area(
        create_area_payload(lab["id"], name="SAA-X", capacity_containers=5),
        make_lab_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_closeout_by_other_labs_pi_forbidden(api):
    """PRD §3.8: "when the actor is a `PrincipalInvestigator`, the acting `X-User-ID`
    must equal the lab's `pi_worker_id`, otherwise `ERR_FORBIDDEN_OWNERSHIP`."
    PRD §2.1: "a request that passes the role check but violates an ownership scope
    is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/errors/closeout_by_other_labs_pi_forbidden
    """
    lab_a = create_lab(name="Lab OA", room="124")
    lab_b = create_lab(name="Lab OB", room="125")
    pi_a = add_worker(lab_a["id"], full_name="Dr. Ay", role_in_lab="PI")
    pi_b = add_worker(lab_b["id"], full_name="Dr. Bee", role_in_lab="PI")

    res = api.closeout_lab(lab_a["id"], make_pi_headers(pi_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    assert get_lab(lab_a["id"])["status"] == "ACTIVE"

    closed = validate_success(api.closeout_lab(lab_a["id"], make_pi_headers(pi_a["id"])), 200)
    assert closed["status"] == "CLOSING", "the lab's own PI may close it out"


def test_worker_cannot_complete_others_training(api):
    """PRD §3.1: "the acting operator must be either the assigned worker themselves
    (the header matches the assignment's `worker_id`) or the lab's PI (the header
    matches the lab's `pi_worker_id`), and anyone else is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."
    PRD §3.1: "Completing the training moves it from `ASSIGNED` to `COMPLETED` and
    stamps `completed_at` with the logical now"

    Design: Corner/errors/worker_cannot_complete_others_training_forbidden
    """
    lab = create_lab(name="Lab OW", department="Biology", building="Hall B", room="212")
    pi = add_worker(lab["id"], full_name="Dr. Py", role_in_lab="PI")
    other = add_worker(lab["id"], full_name="Rita Res", role_in_lab="RESEARCHER")
    assignment = get_success_data(
        api.create_training_assignment(
            create_training_payload(lab["id"], pi["id"], hazard_class="TOXIC"),
            ADMIN,
        )
    )

    res = api.complete_training_assignment(
        assignment["id"], make_lab_member_headers(other["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    completed = validate_success(
        api.complete_training_assignment(assignment["id"], make_pi_headers(pi["id"])), 200
    )
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] is not None


def test_second_pi_worker_rejected(api):
    """PRD §3.1: "A lab has at most one PI-role worker: when a worker is created with
    `role_in_lab` equal to `PI`, the lab's `pi_worker_id` is automatically set to
    the new worker's `id` and the lab's `version` increments by 1, and attempting to
    add a second PI to a lab that already has one is rejected with
    `ERR_PI_ALREADY_ASSIGNED` (HTTP 409)."

    Design: Corner/validations/second_pi_worker_rejected
    """
    lab, pi = create_lab_with_pi(name="Lab P2", room="110")
    assert get_lab(lab["id"])["pi_worker_id"] == pi["id"]

    res = api.create_worker(
        {"lab_id": lab["id"], "full_name": "Dr. Second", "role_in_lab": "PI"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_PI_ALREADY_ASSIGNED)
    assert get_lab(lab["id"])["pi_worker_id"] == pi["id"], (
        "the original PI assignment survives the rejected second-PI create"
    )


def test_duplicate_barcode_same_lab_only(api):
    """PRD §3.2: "A `PrincipalInvestigator` or `LabMember` registers a new container
    with a payload containing the `lab_id`, a `barcode` unique within that lab" and
    "with `ERR_DUPLICATE_BARCODE` (HTTP 409) when the barcode already exists within
    the lab."

    Design: Corner/validations/duplicate_barcode_same_lab_only
    """
    lab1 = create_lab(name="Lab Q1", room="111")
    lab2 = create_lab(name="Lab Q2", room="112")
    pi1 = add_worker(lab1["id"], full_name="Dr. One", role_in_lab="PI")
    pi2 = add_worker(lab2["id"], full_name="Dr. Two", role_in_lab="PI")

    validate_success(
        api.create_container(
            create_container_payload(lab1["id"], barcode="DUP-1", quantity_value=1.0),
            make_pi_headers(pi1["id"]),
        ),
        201,
    )

    res = api.create_container(
        create_container_payload(
            lab1["id"], barcode="DUP-1", chemical_name="Methanol", quantity_value=2.0
        ),
        make_pi_headers(pi1["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_BARCODE)

    cross_lab = validate_success(
        api.create_container(
            create_container_payload(
                lab2["id"], barcode="DUP-1", chemical_name="Methanol", quantity_value=2.0
            ),
            make_pi_headers(pi2["id"]),
        ),
        201,
    )
    assert cross_lab["barcode"] == "DUP-1", "barcode uniqueness is scoped within a lab"
