"""Per-family not-found codes and the reverse-reachability listing filters."""

from test_helpers import (
    ADMIN,
    COURSE_EXT_050,
    COURSE_EXT_150,
    REGISTRAR,
    ApiErrorId,
    assert_certificate_number,
    award_completion,
    cite_record,
    create_instructor_contract_payload,
    create_offering_payload,
    deposit,
    issue_voucher,
    new_account,
    new_course,
    new_petition,
    open_refund_request,
    read_instructor,
    record_attendance,
    reset_clock,
    setup_census_locked_offering,
    validate_error,
    validate_paginated,
    validate_success,
)

MICRO_OFFERING = {"session_count": 4, "tuition_cents": 25000}


def test_unknown_path_ids_return_their_own_not_found_codes(api):
    """PRD 2.9: "Each resource type has its own not-found code:
    `ERR_COURSE_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_LEARNER_NOT_FOUND`,
    `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_COMPLETION_RECORD_NOT_FOUND`, `ERR_PETITION_NOT_FOUND` and
    `ERR_REQUEST_NOT_FOUND`, each returned with HTTP 404."
    PRD 2.8: "Path existence — every resource named by a path segment exists, validated
    left to right; otherwise the not-found code for the first unresolvable segment."

    Design: Corner/errors/unknown_path_ids_return_their_specific_not_found_errors
    """
    reset_clock()
    cases = [
        (
            api.get_registration("00000000-0000-4000-8000-000000000001", REGISTRAR),
            ApiErrorId.ERR_REGISTRATION_NOT_FOUND,
        ),
        (
            api.get_petition("00000000-0000-4000-8000-000000000002", REGISTRAR),
            ApiErrorId.ERR_PETITION_NOT_FOUND,
        ),
        (
            api.get_voucher("00000000-0000-4000-8000-000000000003", REGISTRAR),
            ApiErrorId.ERR_VOUCHER_NOT_FOUND,
        ),
        (
            api.get_instructor_contract("00000000-0000-4000-8000-000000000004", REGISTRAR),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND,
        ),
    ]
    for response, expected in cases:
        validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"


def test_remaining_resource_families_report_their_own_not_found_codes(api):
    """PRD 2.9: "Each resource type has its own not-found code:
    `ERR_COURSE_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_LEARNER_NOT_FOUND`,
    `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_COMPLETION_RECORD_NOT_FOUND`, `ERR_PETITION_NOT_FOUND` and
    `ERR_REQUEST_NOT_FOUND`, each returned with HTTP 404."
    PRD 2.8: "Body existence — every foreign key supplied in the request body resolves
    to an existing row, covering `course_id`, `learner_id`, `instructor_id`,
    `offering_id`, `voucher_id`, `target_offering_id`, `completion_record_id`,
    `prerequisite_course_id` and `target_course_id`; otherwise the corresponding
    not-found code."

    Design: Corner/errors/unknown_ids_in_remaining_resource_families_return_not_found
    """
    reset_clock()
    course = new_course(**COURSE_EXT_050)
    offering = validate_success(
        api.create_offering(
            create_offering_payload(course["id"], session_count=4, tuition_cents=25000),
            ADMIN,
        ),
        201,
    )

    validate_error(
        api.get_offering("00000000-0000-4000-8000-000000000011", REGISTRAR),
        ApiErrorId.ERR_OFFERING_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_learner("00000000-0000-4000-8000-000000000012", REGISTRAR),
        ApiErrorId.ERR_LEARNER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_corporate_account("00000000-0000-4000-8000-000000000013", REGISTRAR),
        ApiErrorId.ERR_ACCOUNT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_completion_record("00000000-0000-4000-8000-000000000014", REGISTRAR),
        ApiErrorId.ERR_COMPLETION_RECORD_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_refund_transfer_request("00000000-0000-4000-8000-000000000015", REGISTRAR),
        ApiErrorId.ERR_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_instructor_contract(
            create_instructor_contract_payload(
                offering["id"], "00000000-0000-4000-8000-000000000016"
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INSTRUCTOR_NOT_FOUND,
        404,
    )
    _, meta = validate_paginated(
        api.list_instructor_contracts(ADMIN, params={"offering_id": offering["id"]})
    )
    assert meta["total_count"] == 0


def test_every_declared_foreign_key_is_reachable_from_its_parent(api):
    """PRD 2.3: "Collection endpoints also accept domain filters, and those filters are
    the only channel through which a client can traverse a relationship backwards."
    PRD 2.3: "Offerings may be filtered by `course_id`, `term_code`, `status` and
    `scheduling_mode`. Vouchers may be filtered by `corporate_account_id`,
    `assigned_learner_id` and `status`. Registrations may be filtered by `offering_id`,
    `learner_id`, `voucher_id`, `transferred_to_registration_id`, `enrollment_status`
    and `payment_status`. Instructor contracts may be filtered by `offering_id`,
    `instructor_id` and `status`. Completion records may be filtered by
    `registration_id`, `learner_id` and `status`. Refund and transfer requests may be
    filtered by `registration_id`, `target_offering_id`, `status` and `request_type`.
    Credit-for-prior-learning petitions may be filtered by `learner_id`,
    `target_course_id` and `status`."
    PRD 3.10: "Because a citation binds a petition to a completion record, the
    relationship is navigable from both ends: the citations of a petition can be listed
    from the petition, and the citations referencing a given completion record can be
    listed from that record — the latter being exactly what the `Registrar` needs before
    attempting a revocation."

    Design: Corner/endpoints/reverse_reachability_lists_resolve_every_declared_foreign_key
    """
    reset_clock()
    scene = setup_census_locked_offering(
        num_learners=2, course_spec=COURSE_EXT_050, offering_overrides=MICRO_OFFERING
    )
    ada, ben = scene["seats"][0], scene["seats"][1]
    record_attendance(ada["registration_id"], 4, scene["instructor_id"])
    record = award_completion(ada["registration_id"], scene["instructor_id"])

    lab_course = new_course(**COURSE_EXT_150)
    petition = new_petition(ada["learner_id"], lab_course["id"])
    citation = cite_record(petition["id"], record["id"], ada["learner_id"])
    request = open_refund_request(ben["registration_id"], request_type="REFUND")

    account = new_account()
    funded = deposit(account["id"], 200000)
    voucher = issue_voucher(account["id"], 200000, funded["version"])

    checks = [
        (api.list_offerings(REGISTRAR, params={"course_id": scene["course_id"]}),
         scene["offering_id"]),
        (api.list_vouchers(REGISTRAR, params={"corporate_account_id": account["id"]}),
         voucher["id"]),
        (api.list_instructor_contracts(REGISTRAR, params={"offering_id": scene["offering_id"]}),
         scene["contract_id"]),
        (api.list_completion_records(REGISTRAR, params={"learner_id": ada["learner_id"]}),
         record["id"]),
        (api.list_citations_for_record(record["id"], REGISTRAR), citation["id"]),
        (api.list_petitions(REGISTRAR, params={"learner_id": ada["learner_id"]}),
         petition["id"]),
        (api.list_petition_citations(petition["id"], REGISTRAR), citation["id"]),
        (api.list_refund_transfer_requests(
            REGISTRAR, params={"registration_id": ben["registration_id"]}), request["id"]),
    ]
    for response, expected_id in checks:
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (
            f"Expected exactly one child row, got {meta['total_count']}"
        )
        assert rows[0]["id"] == expected_id

    fetched = validate_success(api.get_completion_record(record["id"], REGISTRAR))
    assert_certificate_number(fetched, "2026FA", 1)
    assert validate_success(
        api.get_refund_transfer_request(request["id"], REGISTRAR)
    )["status"] == "SUBMITTED"
    assert read_instructor(scene["instructor_id"])["active_contract_count"] == 1
