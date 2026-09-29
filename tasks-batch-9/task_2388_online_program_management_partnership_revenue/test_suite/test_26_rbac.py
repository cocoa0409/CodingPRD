"""Role and tenancy authorisation: the endpoint gate, the per-action map, tenancy and one allow."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_partner_account_lead_headers,
    make_provost_headers,
)


class TestEndpointRoleGate:
    def test_the_provost_cannot_create_a_program(self, api):
        """Outranking the partner on every approval gate buys no write access to program creation.

        PRD: "When the role named on a request is a recognised role but is not among the roles
        authorised for the endpoint being called (see the table in §4), the request fails with
        `ERR_ROLE_NOT_PERMITTED`."
        PRD: "| POST | `/programs` | Create a Program in DRAFT under an EXECUTED Partnership and
        compute its screening demand score | PartnerAccountLead |"
        PRD: "The governance model is one of segregated duties rather than a simple permission
        hierarchy, and two of its rules are enforced against recorded identities rather than against
        roles."

        Design: Corner/rbac/provost_cannot_create_a_program
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        response = api.create_program(
            factories.program_payload(ps_id), headers=make_provost_headers()
        )

        validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        summary = validate_success(
            api.get_revenue_summary(ps_id, headers=make_provost_headers())
        )
        assert summary["program_count"] == 0

    def test_the_compliance_auditor_cannot_reach_the_statement_action_endpoint(self, api):
        """The read-and-certify role is stopped at the endpoint gate, one rung above the action map.

        PRD: "| POST | `/remittance-statements/{id}/actions` | Drive the settlement lifecycle:
        APPROVE, DISPUTE, RESOLVE, REMIT, RECALCULATE | UniversityProvost, UniversityBursar,
        PartnerAccountLead |"
        PRD: "The named role appears in the called endpoint's authorised-role list, on every endpoint
        — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/compliance_auditor_cannot_reach_the_statement_action_endpoint
        """
        context = fixtures.build_september_statement(api, credits_completed=None)
        statement = context["statement"]
        assert statement["status"] == "CALCULATED"

        response = api.post_statement_action(
            statement["id"],
            factories.statement_action_payload("RECALCULATE"),
            headers=make_compliance_auditor_headers(),
        )

        validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        assert fixtures.read_statement(api, statement["id"])["status"] == "CALCULATED"


class TestPerActionRoleMap:
    def test_the_partner_may_submit_a_course_but_never_approve_it(self, api):
        """A permitted endpoint with a reserved action value fails one rung below the endpoint gate.

        PRD: "On the five multi-action endpoints — partnership contract actions, program lifecycle
        actions, course design actions, settlement statement actions, and enrollment academic actions
        — the acting role is permitted for the specific action value supplied, otherwise
        `ERR_ACTION_ROLE_NOT_PERMITTED` (403)."
        PRD: "among course design actions, `START_DESIGN` and `SUBMIT_FOR_FACULTY_REVIEW` are
        `PartnerAccountLead`-only while `REQUEST_REVISION`, `APPROVE` and `RETIRE` are
        `FacultyChair`-only"
        PRD: "Academic content approval is reserved to `FacultyChair` alone — the partner may draft
        and submit courseware but may never sign off on it."

        Design: Corner/rbac/partner_lead_cannot_approve_a_course_design
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        course = fixtures.add_course(api, ps_id, program["id"])
        fixtures.start_course_design(api, ps_id, course["id"])
        submitted = fixtures.submit_course_for_faculty_review(api, ps_id, course["id"])
        assert submitted["design_status"] == "FACULTY_REVIEW"

        response = api.post_course_design_action(
            course["id"],
            factories.design_action_payload(
                "APPROVE", faculty_approver_name=fixtures.FACULTY_APPROVER_NAME
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.ACTION_ROLE_NOT_PERMITTED.value, 403)

        stored = fixtures.read_course(api, course["id"])
        assert stored["design_status"] == "FACULTY_REVIEW"
        assert stored["faculty_approver_name"] is None


class TestPartnerTenancy:
    def test_a_peer_partner_cannot_write_into_another_partnerships_program(self, api):
        """The role is right and the payload is well formed; only the acting identity is foreign.

        PRD: "When `X-User-Role` is `PartnerAccountLead`, `X-User-ID` is the `id` of the acting
        `Partnership`: the partner's identity *is* the partnership it manages."
        PRD: "A `PartnerAccountLead` acting on a resource governed by any other partnership is
        rejected with `ERR_PARTNERSHIP_SCOPE_VIOLATION`, and this applies to every endpoint whose
        authorised-role list includes `PartnerAccountLead`, reads included."
        PRD: "When the acting role is `PartnerAccountLead`, `X-User-ID` equals the `id` of the
        partnership governing the target resource, resolved as described in §2.1 — otherwise
        `ERR_PARTNERSHIP_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/partner_lead_of_one_partnership_cannot_touch_another_partnerships_program
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        home = fixtures.create_executed_partnership(api)
        program = fixtures.create_program(api, home["id"])
        pg_id = program["id"]

        peer = fixtures.create_executed_partnership(
            api,
            university_name="Lakeshore University",
            university_ipeds_id="224999",
            exclusivity_cip_codes=factories.OMIT,
            bundled_services_exception_claimed=factories.OMIT,
        )

        response = api.create_course(
            pg_id,
            factories.course_payload(
                course_code="MBA-777",
                title="Cross-tenant Injection",
                content_owner="PARTNER",
                design_cost_cents=100000,
                required_for_launch=factories.OMIT,
            ),
            headers=make_partner_account_lead_headers(peer["id"]),
        )

        validate_error(response, ApiErrorId.PARTNERSHIP_SCOPE_VIOLATION.value, 403)


class TestBursarAllow:
    def test_the_bursar_posts_tuition_and_the_first_payment_activates_the_student(self, api):
        """The positive control: an immutable ledger entry, an ACTIVE student and a synced ledger.

        PRD: "Entries carry a `generated_by` marker that the server sets: `BURSAR_POST` for an entry
        a bursar posts by hand, and `WITHDRAWAL_REFUND` for the compensating entry the withdrawal
        cascade creates on its own."
        PRD: "The very first `PAYMENT` entry has a further effect: it takes the enrollment `ENROLLED
        → ACTIVE`, because a student who has paid something is academically live."
        PRD: "Each posting recomputes the enrollment's `collected_cents` and `refunded_cents` and the
        partnership's `collected_tuition_cents`, per the conservation rule of §2.7."

        Design: Corner/rbac/bursar_may_post_tuition_on_the_shared_payment_endpoint
        """
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]
        lead = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        enrollment = fixtures.enroll_lead(api, lead["id"])
        assert enrollment["tuition_charged_cents"] == 562500
        assert enrollment["status"] == "ENROLLED"

        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        entry = validate_success(
            api.create_tuition_payment(
                enrollment["id"],
                factories.tuition_payment_payload(
                    amount_cents=300000, reference_note="Partial term payment"
                ),
                headers=make_bursar_headers(),
            ),
            201,
        )

        assert entry["amount_cents"] == 300000
        assert entry["entry_type"] == "PAYMENT"
        assert entry["generated_by"] == "BURSAR_POST"

        stored = fixtures.read_enrollment(api, enrollment["id"])
        assert stored["collected_cents"] == 300000
        assert stored["refunded_cents"] == 0
        assert stored["status"] == "ACTIVE"
        assert fixtures.read_partnership(api, ps_id)["collected_tuition_cents"] == 300000
