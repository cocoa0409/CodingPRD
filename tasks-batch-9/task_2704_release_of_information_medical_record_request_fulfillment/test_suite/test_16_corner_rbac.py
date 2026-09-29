"""RBAC corners: the role column, the entity-backed Requester's two behaviours, the
dual-hat segregation refusal and the two-role revoke route."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant
from test_helpers.test_users import (
    ANALYST_1,
    BILLING_1,
    INTAKE_1,
    PLATFORM_ADMIN,
    PRIVACY_1,
    REVIEWER_1,
    REVIEWER_2,
    ROLE_INTAKE_SPECIALIST,
    ROLE_RELEASE_REVIEWER,
    make_headers,
    make_requester_headers,
)

DUAL_HAT_USER = "u-dual-1"
DUAL_AS_INTAKE = make_headers(DUAL_HAT_USER, ROLE_INTAKE_SPECIALIST)
DUAL_AS_REVIEWER = make_headers(DUAL_HAT_USER, ROLE_RELEASE_REVIEWER)


# --------------------------------------------------------------------------
# role_matrix_denies_writes_outside_each_roles_column_unauthorized
# --------------------------------------------------------------------------
def _accepted_request_in_compilation(api):
    """One accepted third-party request, so every role below has a real target to miss."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    return world, request["id"]


def _seven_writes_outside_their_column(api, world, request_id):
    """Seven otherwise-valid calls, each made by a role the addressed endpoint omits."""
    return [
        (
            "analyst issuing a denial",
            api.create_denial(f.denial_payload(request_id, "RECORD_NOT_MAINTAINED"), ANALYST_1),
        ),
        (
            "billing clerk opening a segment",
            api.create_record_segment(
                f.record_segment_payload(request_id, "GENERAL_MEDICAL", "EHR_CURRENT"), BILLING_1
            ),
        ),
        (
            "privacy officer pricing the request",
            api.create_invoice(
                f.invoice_payload(request_id, fx.request_version(api, request_id)), PRIVACY_1
            ),
        ),
        (
            "intake specialist releasing its own request",
            api.release_request(request_id, f.release_payload("intake wants it out"), INTAKE_1),
        ),
        (
            "platform admin accepting an accepted request",
            api.intake_decision(request_id, f.intake_decision_payload("ACCEPT"), PLATFORM_ADMIN),
        ),
        (
            "facility admin intaking a request",
            api.create_request(
                f.third_party_request_payload(
                    world["facility_id"],
                    world["patient_id"],
                    world["requester_id"],
                    world["authorization_id"],
                    date_range_start="2023-01-01",
                    date_range_end="2023-12-31",
                ),
                world["facility_admin_headers"],
            ),
        ),
        (
            "requester listing compiled segments",
            api.list_record_segments(
                world["requester_headers"], {"request_id": request_id, "limit": 10}
            ),
        ),
    ]


def test_seven_roles_pointed_at_a_write_outside_their_column_are_all_refused(api):
    """Nothing but the role differs, so nothing but the role can be the cause.

    PRD: "A call whose `X-User-Role` is not among the roles the addressed endpoint permits is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/role_matrix_denies_writes_outside_each_roles_column_unauthorized
    """
    world, request_id = _accepted_request_in_compilation(api)

    attempts = _seven_writes_outside_their_column(api, world, request_id)

    assert len(attempts) == 7
    for label, response in attempts:
        assert response.status_code == 403, label
        validate_error(response, e.ERR_UNAUTHORIZED_ROLE, 403)


def test_the_role_gate_answers_ahead_of_segregation_state_and_list_scoping(api):
    """Priority 2 runs before priorities 9 and 10, and before Requester narrowing.

    PRD: "Validation is a single ordered pipeline, and the **first** violated rule determines the response; later violations are not reported."

    Design: Corner/rbac/role_matrix_denies_writes_outside_each_roles_column_unauthorized
    """
    world, request_id = _accepted_request_in_compilation(api)
    before = fx.read_request(api, request_id)
    assert before["intake_user_id"] == "u-intake-1"
    assert before["fulfillment_status"] == "COMPILATION"

    attempts = dict(_seven_writes_outside_their_column(api, world, request_id))

    release = attempts["intake specialist releasing its own request"].json()["data"]
    assert release["error_id"] == e.ERR_UNAUTHORIZED_ROLE
    assert release["error_id"] != e.ERR_SEGREGATION_OF_DUTIES
    assert release["error_id"] != e.ERR_REQUEST_STATE_INVALID
    second_accept = attempts["platform admin accepting an accepted request"].json()["data"]
    assert second_accept["error_id"] == e.ERR_UNAUTHORIZED_ROLE
    assert second_accept["error_id"] != e.ERR_REQUEST_STATE_INVALID
    listing = attempts["requester listing compiled segments"]
    assert listing.json()["response_type"] == "error"
    assert listing.json()["data"]["error_id"] == e.ERR_UNAUTHORIZED_ROLE

    after = fx.read_request(api, request_id)
    assert after["fulfillment_status"] == "COMPILATION"
    assert after["version"] == before["version"]
    assert after["released_at"] is None


def test_none_of_the_seven_refusals_created_a_row(api):
    """Every collection the seven calls addressed is exactly as it was.

    PRD: "A call whose `X-User-Role` is not among the roles the addressed endpoint permits is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/role_matrix_denies_writes_outside_each_roles_column_unauthorized
    """
    world, request_id = _accepted_request_in_compilation(api)
    for _, response in _seven_writes_outside_their_column(api, world, request_id):
        validate_error(response, e.ERR_UNAUTHORIZED_ROLE, 403)

    _, segments = fx.list_segments_for(api, request_id)
    assert segments["total_count"] == 0
    _, denials = validate_paginated(
        api.list_denials(PRIVACY_1, {"request_id": request_id, "limit": 10})
    )
    assert denials["total_count"] == 0
    _, invoices = fx.list_invoices_for(api, request_id)
    assert invoices["total_count"] == 0
    _, requests = validate_paginated(
        api.list_requests(INTAKE_1, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert requests["total_count"] == 1


# --------------------------------------------------------------------------
# requester_reads_error_on_foreign_ids_and_narrow_silently_on_lists
# --------------------------------------------------------------------------
def _two_attorneys_on_one_patient(api):
    """One patient, two attorneys, one authorization and one request each."""
    world = fx.base_world(api)
    scenario = {"world": world}
    for tag in ("a", "b"):
        attorney = fx.make_attorney(api)
        authorization = fx.make_authorization(api, world["patient_id"], attorney["id"])
        request = get_success_data(
            api.create_request(
                f.third_party_request_payload(
                    world["facility_id"],
                    world["patient_id"],
                    attorney["id"],
                    authorization["id"],
                ),
                INTAKE_1,
            )
        )
        scenario[tag] = {
            "requester_id": attorney["id"],
            "headers": make_requester_headers(attorney["id"]),
            "authorization_id": authorization["id"],
            "request_id": request["id"],
        }
    return scenario


def test_a_requester_reading_a_foreign_id_directly_is_refused_three_times(api):
    """The entity read, the computed read and the authorization read all check ownership.

    PRD: "Concretely, when a caller acts as `Requester` on any endpoint whose permitted roles include `Requester`, the addressed request — reached directly, or indirectly through an addressed invoice, delivery, denial decision, amendment request or authorization — must have a `requester_id` equal to `X-User-ID`; if it does not, the call is rejected with `ERR_NOT_REQUEST_OWNER` (HTTP 403)."

    Design: Corner/rbac/requester_reads_error_on_foreign_ids_and_narrow_silently_on_lists
    """
    scenario = _two_attorneys_on_one_patient(api)
    a, b = scenario["a"], scenario["b"]

    validate_error(
        api.get_request(b["request_id"], a["headers"]), e.ERR_NOT_REQUEST_OWNER, 403
    )
    validate_error(
        api.get_turnaround(b["request_id"], a["headers"]), e.ERR_NOT_REQUEST_OWNER, 403
    )
    validate_error(
        api.get_authorization(b["authorization_id"], a["headers"]),
        e.ERR_NOT_REQUEST_OWNER,
        403,
    )

    own_request = validate_success(api.get_request(a["request_id"], a["headers"]), 200)
    assert own_request["requester_id"] == a["requester_id"]
    validate_success(api.get_turnaround(a["request_id"], a["headers"]), 200)
    own_authorization = validate_success(
        api.get_authorization(a["authorization_id"], a["headers"]), 200
    )
    assert own_authorization["requester_id"] == a["requester_id"]


def test_the_same_caller_meets_silent_narrowing_on_every_list(api):
    """No error on a list, not even when the caller names the other requester explicitly.

    PRD: "List endpoints behave differently: rather than erroring, a list read performed by a `Requester` is silently narrowed to rows whose `requester_id` equals `X-User-ID`."

    Design: Corner/rbac/requester_reads_error_on_foreign_ids_and_narrow_silently_on_lists
    """
    scenario = _two_attorneys_on_one_patient(api)
    a, b = scenario["a"], scenario["b"]

    own_rows, own_meta = validate_paginated(api.list_requests(a["headers"], {"limit": 10}))
    assert own_meta["total_count"] == 1
    assert [row["id"] for row in own_rows] == [a["request_id"]]

    foreign_rows, foreign_meta = validate_paginated(
        api.list_requests(a["headers"], {"requester_id": b["requester_id"], "limit": 10})
    )
    assert foreign_meta["total_count"] == 0
    assert foreign_rows == []

    auth_rows, auth_meta = validate_paginated(
        api.list_authorizations(
            a["headers"], {"patient_id": scenario["world"]["patient_id"], "limit": 10}
        )
    )
    assert auth_meta["total_count"] == 1
    assert [row["id"] for row in auth_rows] == [a["authorization_id"]]


def test_a_staff_role_sees_the_unnarrowed_set_the_requester_could_not(api):
    """The narrowing comes from the caller's identity, not from the data.

    PRD: "When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `Requester`; ownership checks on any resource that references a `Requester` compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/rbac/requester_reads_error_on_foreign_ids_and_narrow_silently_on_lists
    """
    scenario = _two_attorneys_on_one_patient(api)
    a, b = scenario["a"], scenario["b"]

    staff_rows, staff_meta = validate_paginated(api.list_requests(PRIVACY_1, {"limit": 10}))
    assert staff_meta["total_count"] == 2
    assert {row["id"] for row in staff_rows} == {a["request_id"], b["request_id"]}

    _, staff_auth_meta = validate_paginated(
        api.list_authorizations(
            PRIVACY_1, {"patient_id": scenario["world"]["patient_id"], "limit": 10}
        )
    )
    assert staff_auth_meta["total_count"] == 2
    validate_success(api.get_request(b["request_id"], PRIVACY_1), 200)


# --------------------------------------------------------------------------
# release_by_the_intake_user_is_refused_although_the_role_is_correct
# --------------------------------------------------------------------------
def _dual_hat_request_paid_and_release_ready(api):
    """u-dual-1 takes in and accepts the request; 25 pages are compiled, priced at 2188 and
    paid, so only the identity pairing can still refuse the release."""
    world = fx.third_party_world(api)
    request = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                world["facility_id"],
                world["patient_id"],
                world["requester_id"],
                world["authorization_id"],
            ),
            DUAL_AS_INTAKE,
        )
    )
    get_success_data(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), DUAL_AS_INTAKE)
    )
    fx.add_retrieved_segment(api, request["id"], 25)
    fx.complete_compilation(api, request["id"])
    fx.run_sensitive_review(api, request["id"], [], headers=REVIEWER_1)
    invoice = fx.invoice_and_pay(api, request["id"])
    return world, request["id"], invoice


def test_the_intake_user_wearing_the_reviewer_role_is_refused_on_identity(api):
    """The role is permitted and the money is settled, so only intake_user_id is left.

    PRD: "The acting `X-User-ID` must differ from the request's `intake_user_id`, or the release is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/release_by_the_intake_user_is_refused_although_the_role_is_correct
    """
    _, request_id, invoice = _dual_hat_request_paid_and_release_ready(api)
    before = fx.read_request(api, request_id)
    assert before["intake_user_id"] == DUAL_HAT_USER
    assert before["fulfillment_status"] == "RELEASE_READY"
    assert before["billing_status"] == "PAID"
    assert fx.read_invoice(api, invoice["id"])["status"] == "PAID"

    response = api.release_request(
        request_id, f.release_payload("closing my own intake"), DUAL_AS_REVIEWER
    )

    data = validate_error(response, e.ERR_SEGREGATION_OF_DUTIES, 403)
    assert data["error_id"] != e.ERR_UNAUTHORIZED_ROLE
    assert data["error_id"] != e.ERR_INVOICE_UNSETTLED
    after = fx.read_request(api, request_id)
    assert after["fulfillment_status"] == "RELEASE_READY"
    assert after["released_at"] is None
    assert after["release_reviewer_user_id"] is None
    assert after["version"] == before["version"]


def test_a_second_reviewer_releases_the_very_same_request_unchanged(api):
    """The only difference between the refused call and the accepted one is X-User-ID.

    PRD: "A `ReleaseReviewer` releases a request from `RELEASE_READY` to `RELEASED`, supplying an optional `release_note`."

    Design: Corner/rbac/release_by_the_intake_user_is_refused_although_the_role_is_correct
    """
    _, request_id, _ = _dual_hat_request_paid_and_release_ready(api)
    validate_error(
        api.release_request(request_id, f.release_payload("mine to close"), DUAL_AS_REVIEWER),
        e.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    released = validate_success(
        api.release_request(request_id, f.release_payload("mine to close"), REVIEWER_2), 200
    )

    assert released["fulfillment_status"] == "RELEASED"
    assert released["released_at"] == Instant("2026-08-01T00:00:00Z")
    assert released["release_reviewer_user_id"] == "u-review-2"


def test_the_reviewer_who_ran_the_sensitive_review_is_not_disqualified(api):
    """Release tracks exactly one pairing, and the sensitive-review pass is not part of it.

    PRD: "Releasing a request requires that `X-User-ID` differ from the request's `intake_user_id`."

    Design: Corner/rbac/release_by_the_intake_user_is_refused_although_the_role_is_correct
    """
    _, request_id, _ = _dual_hat_request_paid_and_release_ready(api)

    released = validate_success(
        api.release_request(request_id, f.release_payload("reviewed and released"), REVIEWER_1), 200
    )

    assert released["fulfillment_status"] == "RELEASED"
    assert released["release_reviewer_user_id"] == "u-review-1"
    assert released["released_at"] == Instant("2026-08-01T00:00:00Z")


# --------------------------------------------------------------------------
# authorization_revoke_is_shared_by_privacy_officer_and_the_owning_requester
# --------------------------------------------------------------------------
def _two_authorizations_written_by_two_roles(api):
    """One patient, two attorneys: A's authorization is written by intake, B's by the privacy
    officer, so the shared creation route is exercised from both columns."""
    world = fx.base_world(api)
    patient_id = world["patient_id"]
    attorney_a = fx.make_attorney(api)
    attorney_b = fx.make_attorney(api)

    authorization_a = validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, attorney_a["id"], fx.patient_version(api, patient_id)),
            INTAKE_1,
        ),
        201,
    )
    authorization_b = validate_success(
        api.create_authorization(
            f.authorization_payload(patient_id, attorney_b["id"], fx.patient_version(api, patient_id)),
            PRIVACY_1,
        ),
        201,
    )
    return {
        "world": world,
        "a": {
            "headers": make_requester_headers(attorney_a["id"]),
            "authorization": authorization_a,
        },
        "b": {
            "headers": make_requester_headers(attorney_b["id"]),
            "authorization": authorization_b,
        },
    }


def test_the_shared_creation_route_accepts_both_writers_and_advances_the_patient_twice(api):
    """Two roles write two VALID authorizations, and each accepted write moves the patient.

    PRD: "A successful authorization creation increments the patient's `version` by 1, which is what makes the guard bite: a new authorization carrying `supersedes_authorization_id` retires the named predecessor and is exempt from the coverage-window overlap check, so a specialist who has not observed the patient's changed authorization set would otherwise retire an authorization it never saw."

    Design: Corner/rbac/authorization_revoke_is_shared_by_privacy_officer_and_the_owning_requester
    """
    scenario = _two_authorizations_written_by_two_roles(api)

    assert scenario["a"]["authorization"]["status"] == "VALID"
    assert scenario["b"]["authorization"]["status"] == "VALID"
    assert scenario["a"]["authorization"]["id"] != scenario["b"]["authorization"]["id"]
    assert fx.patient_version(api, scenario["world"]["patient_id"]) == 3


def test_the_owning_requester_may_revoke_only_the_authorization_it_is_named_on(api):
    """A perfectly valid Requester is still refused by ownership on someone else's paper.

    PRD: "**Revocation** is shared by `PrivacyOfficer` and the `Requester` named on the authorization, takes a `revocation_reason`, and is permitted only from `VALID` or `DEFECTIVE` — from `REVOKED`, `EXPIRED` or `SUPERSEDED` it is refused with `ERR_AUTHORIZATION_STATE_INVALID`."

    Design: Corner/rbac/authorization_revoke_is_shared_by_privacy_officer_and_the_owning_requester
    """
    scenario = _two_authorizations_written_by_two_roles(api)
    a, b = scenario["a"], scenario["b"]

    validate_error(
        api.revoke_authorization(b["authorization"]["id"], f.revoke_payload(), a["headers"]),
        e.ERR_NOT_REQUEST_OWNER,
        403,
    )
    untouched = validate_success(
        api.get_authorization(b["authorization"]["id"], PRIVACY_1), 200
    )
    assert untouched["status"] == "VALID"
    assert untouched["revoked_at"] is None

    revoked = validate_success(
        api.revoke_authorization(a["authorization"]["id"], f.revoke_payload(), a["headers"]), 200
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == Instant("2026-08-01T00:00:00Z")


def test_the_privacy_officer_needs_no_ownership_but_still_needs_a_live_status(api):
    """Sharing the route does not reopen a terminal status, and never required ownership.

    PRD: "The five states an authorization may occupy are `VALID`, `DEFECTIVE`, `REVOKED`, `EXPIRED` and `SUPERSEDED`; the last three are terminal."

    Design: Corner/rbac/authorization_revoke_is_shared_by_privacy_officer_and_the_owning_requester
    """
    scenario = _two_authorizations_written_by_two_roles(api)
    a, b = scenario["a"], scenario["b"]
    validate_success(
        api.revoke_authorization(a["authorization"]["id"], f.revoke_payload(), a["headers"]), 200
    )

    validate_error(
        api.revoke_authorization(a["authorization"]["id"], f.revoke_payload(), PRIVACY_1),
        e.ERR_AUTHORIZATION_STATE_INVALID,
        409,
    )
    officer_revoked = validate_success(
        api.revoke_authorization(b["authorization"]["id"], f.revoke_payload(), PRIVACY_1), 200
    )

    assert officer_revoked["status"] == "REVOKED"
    assert officer_revoked["revoked_at"] == Instant("2026-08-01T00:00:00Z")
    assert officer_revoked["version"] == b["authorization"]["version"] + 1
