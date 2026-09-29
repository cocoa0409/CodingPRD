"""Role authorisation, entity-backed identity and segregation of safety duties."""

from test_helpers import (
    ERR_FORBIDDEN_ROLE,
    ERR_ROLE_IDENTITY_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    assert_posture,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_DATE, CLOCK_TEST_UTC, ELEMENT_NAME_LOW
from test_helpers.factories import element_payload, operational_log_payload
from test_helpers.fixtures import (
    create_course,
    create_element,
    create_safety_officer,
    create_staff_facilitator,
    defect_major_log,
    set_clock,
)
from test_helpers.test_users import (
    PROGRAM_DIRECTOR,
    make_facilitator_headers,
    make_safety_officer_headers,
)

ROGUE_ELEMENT_NAME = "Rogue Element"
DEFECT_NOTE = "Broken cable strand at the north anchor"


class TestDailyOpenBelongsToTheDirector:
    """The checkpoint is operator management's own act and needs no staff identity."""

    def test_the_director_opens_an_unstaffed_site_and_it_scores_rescue_readiness(self, api):
        """The opaque director identity is accepted and the checkpoint still stamps its index.

        PRD 2.1: "It builds courses, installs and retires elements, hires staff,
        records training, registers group clients, posts client payments, designs
        programs, staffs blocks, runs the daily opening checkpoint and may quote a
        booking."

        PRD 2.1: "When `X-User-Role` is `ProgramDirector`, `X-User-ID` is an opaque
        operator identifier that is not tied to any persisted entity; the server may
        accept and log it but never compares it to any row's `id`."

        PRD 2.5: "`rescue_readiness_ok` is false. Result: `CLOSED`, reason
        `RESCUE_READINESS`."

        PRD 3.1: "Step one increments `daily_open_index` and sets
        `last_daily_open_date` to the clock date."

        Design: Corner/rbac/program_director_runs_the_daily_open_checkpoint
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)

        opened = validate_success(api.daily_open(course_id, PROGRAM_DIRECTOR))

        assert_posture(opened, "CLOSED", "RESCUE_READINESS")
        assert opened["daily_open_index"] == 1
        assert opened["last_daily_open_date"] == CLOCK_TEST_DATE
        assert opened["rescue_ready_facilitator_count"] == 0
        assert opened["rescue_readiness_ok"] is False


class TestOperationalLogAuthors:
    """Both the facilitator and the safety officer may file their own pre-use log."""

    def test_a_facilitator_and_a_safety_officer_each_file_their_own_clear_log(self, api):
        """Each author supplies its own identifier, and both writes are accepted.

        PRD 2.1: "A `Facilitator` recording an operational inspection log must supply
        its own identifier as the log's `facilitator_id`."

        PRD 4: "| POST | `/challenge-course/operational-logs` | Record a
        facilitator's operational pre-use inspection of an element. | Facilitator,
        SafetyOfficer |"

        PRD 3.3: "A `CLEAR` result clears that element's daily-inspection gate for
        its `log_date` and updates `last_clear_log_date`, which tracks the `log_date`
        of the newest clear log for the element, ordered by `log_date` descending
        with `created_at` descending as the tie-break."

        PRD 3.3: "`caused_restriction` is false on every other log."

        Design: Corner/rbac/operational_log_accepted_from_both_facilitator_and_safety_officer
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)
        f1_id = create_staff_facilitator(api, course_id)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        log_a = validate_success(
            api.create_operational_log(
                operational_log_payload(l_id, f1_id, "CLEAR"), make_facilitator_headers(f1_id)
            ),
            201,
        )
        log_b = validate_success(
            api.create_operational_log(
                operational_log_payload(l_id, so_id, "CLEAR"),
                make_safety_officer_headers(so_id),
            ),
            201,
        )

        assert log_a["facilitator_id"] == f1_id
        assert log_a["caused_restriction"] is False
        assert log_b["facilitator_id"] == so_id
        assert log_b["caused_restriction"] is False

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"
        assert element["last_clear_log_date"] == CLOCK_TEST_DATE


class TestElementInstallationIsDirectorOnly:
    """Installing hardware is management's decision, not the delivery team's."""

    def test_a_facilitator_cannot_install_an_element(self, api):
        """The role is well formed and simply not authorised for the endpoint.

        PRD 2.1: "If both headers are well formed but the named role is not among the
        roles authorised for the endpoint (see the table in §4), the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD 4: "| POST | `/challenge-course/elements` | Install an element on a
        course, seeding its inspection due date and cycle history. | ProgramDirector
        |"

        PRD 2.5: "The course-level `next_professional_inspection_due_on` is the
        earliest `next_professional_inspection_due_on` among the course's elements
        whose `status` is not `RETIRED`; when the course has no such element the
        value is null and clause 4 cannot fire."

        Design: Corner/rbac/facilitator_creating_an_element_is_forbidden
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        f1_id = create_staff_facilitator(api, course_id)

        validate_error(
            api.create_element(
                element_payload(course_id, "LOW_ELEMENT", element_name=ROGUE_ELEMENT_NAME),
                make_facilitator_headers(f1_id),
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        course = validate_success(api.get_course(course_id, PROGRAM_DIRECTOR))
        assert course["next_professional_inspection_due_on"] is None


class TestNobodyClearsTheirOwnDefect:
    """The countersignature must come from somebody other than the log's author."""

    def test_the_officer_who_filed_the_defect_cannot_return_the_element(self, api):
        """Segregation is checked before the defect-cleared test the same call would fail.

        PRD 2.7: "Returning an element to service may not be performed by the
        facilitator who filed the operational log that restricted it: when the
        element's `restricting_log_id` is set, the acting user must differ from that
        log's `facilitator_id`."

        PRD 2.12: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`. Applies to
        element return-to-service, inspection disposal and incident closure."

        PRD 3.3: "A `DEFECT_MAJOR` result against a `SERVICEABLE` element fires
        Cascade A of §2.6 in full and sets the log's `caused_restriction` to true,
        which is the flag that later identifies this log as the restriction's
        origin."

        Design: Corner/rbac/defect_log_author_cannot_return_the_element_they_restricted
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        so_id = create_safety_officer(api, course_id)
        so_headers = make_safety_officer_headers(so_id)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        bad_log = defect_major_log(api, l_id, so_id, so_headers, defect_note=DEFECT_NOTE)

        validate_error(
            api.return_element_to_service(
                l_id, {"note": "Clearing my own defect"}, so_headers
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["status"] == "RESTRICTED"
        assert element["restricting_log_id"] == bad_log["id"]

        stored_log = validate_success(api.get_operational_log(bad_log["id"], PROGRAM_DIRECTOR))
        assert stored_log["caused_restriction"] is True

        course = validate_success(api.get_course(course_id, PROGRAM_DIRECTOR))
        assert course["restricted_element_count"] == 1


class TestEntityBackedIdentityIsVerifiedFirst:
    """The claimed role must match the discriminator on the row the identifier resolves to."""

    def test_a_staff_facilitator_identity_cannot_act_as_the_safety_officer(self, api):
        """Identity resolution rejects the call before the state precondition is reached.

        PRD 2.1: "When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is the `id` of a
        `Facilitator` record whose `staff_type` is `SAFETY_OFFICER` and whose
        `certification_level` is `LEVEL_3`."

        PRD 2.1: "If the identifier does not resolve to an instance of the backing
        entity, or the resolved instance's discriminator does not match the claimed
        role, the request is rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

        PRD 2.12: "Identity resolution for entity-backed roles —
        `ERR_ROLE_IDENTITY_MISMATCH`. Applies to every endpoint except course
        registration and the clock endpoint."

        Design: Corner/rbac/safety_officer_role_with_a_staff_facilitator_identity_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        f1_id = create_staff_facilitator(api, course_id)
        l_id = create_element(api, course_id, "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW)

        validate_error(
            api.return_element_to_service(
                l_id,
                {"note": "Wrong identity for this role"},
                make_safety_officer_headers(f1_id),
            ),
            ERR_ROLE_IDENTITY_MISMATCH,
            403,
        )

        element = validate_success(api.get_element(l_id, PROGRAM_DIRECTOR))
        assert element["status"] == "SERVICEABLE"
