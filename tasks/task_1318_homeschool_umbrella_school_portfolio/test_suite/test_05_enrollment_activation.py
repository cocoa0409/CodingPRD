"""Enrollment activation prerequisites, withdrawal terminality."""
from test_helpers import (
    ApiErrorId,
    assert_enrollment,
    create_acknowledged_notice,
    create_approved_plan,
    create_curriculum_plan_payload,
    create_notice_payload,
    create_open_year,
    get_success_data,
    setup_registered_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def test_activation_rejected_while_notice_only_filed(api):
    """PRD §3.2: "Activation — `REGISTERED` → `ACTIVE`, performed by a
    `Registrar` — is the year's first compliance checkpoint, and it enforces
    three prerequisites: the academic year must be `OPEN` (else
    `ERR_ACADEMIC_YEAR_NOT_OPEN`); a notice of intent for the enrollment must
    stand `ACKNOWLEDGED` (else `ERR_NOTICE_NOT_ACKNOWLEDGED`); and the
    enrollment's curriculum plan must be `APPROVED` (else
    `ERR_PLAN_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_notice_acknowledged
    """
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Act",
                                      district_code="D-20")
    notice = get_success_data(
        api.create_notice(ctx["enrollment"]["id"], create_notice_payload(district_code="D-20"),
                          ctx["parent_headers"])
    )
    get_success_data(api.file_notice(notice["id"], ctx["parent_headers"]))
    create_approved_plan(ctx["enrollment"], ctx["family"])

    resp = api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_ACKNOWLEDGED)


def test_activation_succeeds_after_notice_acknowledged(api):
    """PRD §3.2: "A successful activation stamps `activated_at` and increments
    the enrollment's `version`."
    PRD §3.2: "a notice of intent for the enrollment must stand `ACKNOWLEDGED`
    (else `ERR_NOTICE_NOT_ACKNOWLEDGED`)"

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_notice_acknowledged
    """
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Act",
                                      district_code="D-20")
    notice = get_success_data(
        api.create_notice(ctx["enrollment"]["id"], create_notice_payload(district_code="D-20"),
                          ctx["parent_headers"])
    )
    get_success_data(api.file_notice(notice["id"], ctx["parent_headers"]))
    create_approved_plan(ctx["enrollment"], ctx["family"])

    resp = api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_ACKNOWLEDGED)

    get_success_data(api.acknowledge_notice(notice["id"], REGISTRAR))
    activated = validate_success(api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert_enrollment(activated)
    assert activated["enrollment_status"] == "ACTIVE"
    assert activated["activated_at"] is not None


def test_activation_requires_approved_plan(api):
    """PRD §3.2: "the enrollment's curriculum plan must be `APPROVED` (else
    `ERR_PLAN_NOT_APPROVED`)."

    Design: Corner/validations/activation_requires_approved_plan
    """
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Ap",
                                      district_code="D-55")
    create_acknowledged_notice(ctx["enrollment"], ctx["family"], district_code="D-55")
    plan = get_success_data(
        api.create_curriculum_plan(
            ctx["enrollment"]["id"], create_curriculum_plan_payload(), ctx["parent_headers"]
        )
    )
    get_success_data(api.submit_curriculum_plan(plan["id"], ctx["parent_headers"]))
    # Plan is SUBMITTED but never reviewed.
    resp = api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)
    enrollment = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["enrollment_status"] == "REGISTERED"


def test_activation_blocked_when_year_not_open(api):
    """PRD §3.2: "the academic year must be `OPEN` (else
    `ERR_ACADEMIC_YEAR_NOT_OPEN`)"
    PRD §3.1: "A new year is `PLANNING`."

    Design: Corner/errors/activation_blocked_when_year_not_open
    """
    from test_helpers import create_academic_year  # local import: PLANNING year

    year = create_academic_year()  # never opened
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Yn",
                                      district_code="D-70")
    create_acknowledged_notice(ctx["enrollment"], ctx["family"], district_code="D-70")
    create_approved_plan(ctx["enrollment"], ctx["family"])

    resp = api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ACADEMIC_YEAR_NOT_OPEN)
    enrollment = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["enrollment_status"] == "REGISTERED"


def test_withdrawn_enrollment_rejects_activation(api):
    """PRD §3.2: "A `Parent` of the owning family, or a `Registrar`, may
    withdraw an enrollment in `REGISTERED` or `ACTIVE`, optionally attaching a
    `reason`; the enrollment lands in the terminal state `WITHDRAWN` with
    `withdrawn_at` stamped and its `version` incremented."
    PRD §2.8: "State feasibility: the target resource's current state must permit
    the operation."

    Design: Corner/state_machines/withdrawn_enrollment_rejects_activation
    """
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam W",
                                      district_code="D-36")
    withdrawn = validate_success(
        api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"reason": "moving"}, ctx["parent_headers"]
        )
    )
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_at"] is not None

    resp = api.activate_enrollment(ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
