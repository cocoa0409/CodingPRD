"""Authentication, role gates and applicant ownership."""
from test_helpers import analyst_headers, caseworker_headers, fiscal_officer_headers
from test_helpers import make_applicant_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx


def test_a_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request other than the logical-clock capability described in §2.5
    must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`,
    declaring the capacity in which that user is acting."
    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "1. **Authentication** — headers present and non-empty;
    `ERR_UNAUTHENTICATED`. Applies to every endpoint except the logical-clock
    capability."

    Design: Corner/errors/request_missing_auth_headers_is_unauthenticated
    """
    response = api._request(
        "POST",
        "/households",
        factories.household_payload(
            head_of_household_name="Corner Unauthenticated Household"
        ),
        {},
    )

    asrt.assert_rejected(response, errs.ERR_UNAUTHENTICATED)
    asrt.assert_page(api.search_cases(analyst_headers()), total_count=0)


def test_a_caseworker_may_not_approve_an_application(api):
    """PRD §2.1: "If the supplied role is not among the roles listed for the target
    endpoint in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.3: "Approval is the path that creates an ongoing assistance case, and it is
    the most heavily guarded operation in the system."
    PRD §3.3: "Nothing else changes and no case is created."

    Design: Corner/rbac/caseworker_cannot_approve_an_application
    """
    built = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Corner Role Approve Household"},
        incomes=(),
    )
    application_id = built["application"]["id"]

    response = api.approve_application(
        application_id, factories.approve_payload("2026-08"), caseworker_headers()
    )

    asrt.assert_rejected(response, errs.ERR_FORBIDDEN_ROLE)
    stored = fx.read_application(api, application_id)
    assert stored["status"] == "DETERMINED"
    asrt.assert_money(stored["determined_benefit_cents"], 41650, "determined benefit")
    asrt.assert_page(
        api.search_cases(
            analyst_headers(), params={"household_id": built["household"]["id"]}
        ),
        total_count=0,
    )


def test_an_applicant_may_not_read_another_households_application(api):
    """PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting
    `Household`; ownership checks on any resource that references a `Household` compare
    the resource's household foreign-key field to `X-User-ID`, directly for
    household-scoped endpoints and transitively through the owning application's
    `household_id` for application-scoped and diversion-scoped endpoints."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_HOUSEHOLD_OWNER` (HTTP 403)."
    PRD §2.8: "6. **Household ownership** — the `Applicant` check described in §2.1;
    `ERR_NOT_HOUSEHOLD_OWNER`."

    Design: Corner/rbac/applicant_cannot_read_another_households_application
    """
    owner = fx.create_household(
        api, head_of_household_name="Corner Owner Household A"
    )
    stranger = fx.create_household(
        api,
        head_of_household_name="Corner Owner Household B",
        household_size=2,
        adult_count=1,
        youngest_child_age_months=40,
    )
    application = fx.create_application(api, owner["id"])

    response = api.get_application(
        application["id"], make_applicant_headers(stranger["id"])
    )

    asrt.assert_rejected(response, errs.ERR_NOT_HOUSEHOLD_OWNER)
    own_read = asrt.assert_accepted(
        api.get_application(application["id"], make_applicant_headers(owner["id"]))
    )
    assert own_read["household_id"] == owner["id"]
    assert own_read["status"] == "RECEIVED"


def test_a_fiscal_officer_may_not_impose_a_work_sanction(api):
    """PRD §2.1: "If the supplied role is not among the roles listed for the target
    endpoint in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "2. **Authorization** — the presented role is listed for the endpoint;
    `ERR_FORBIDDEN_ROLE`. Applies to every endpoint except the logical-clock capability."
    PRD §3.7: "The third exit is the adverse one. An `EligibilitySupervisor` **imposes a
    sanction**, which is reachable from `CONCILIATION` and, when a cure fails, again from
    `CURE_PENDING`."

    Design: Corner/rbac/fiscal_officer_cannot_impose_a_work_sanction
    """
    context = fx.build_active_case(
        api,
        household_overrides={
            "head_of_household_name": "Corner Fiscal Sanction Household"
        },
        incomes=(),
    )
    episode = fx.open_episode(api, context.case_id, allegation_reason="HOURS_SHORTFALL")
    fx.start_conciliation(api, episode["id"])

    response = api.impose_sanction(episode["id"], fiscal_officer_headers())

    asrt.assert_rejected(response, errs.ERR_FORBIDDEN_ROLE)
    stored = fx.read_episode(api, episode["id"])
    assert stored["status"] == "CONCILIATION"
    assert stored["sanction_level"] == 0
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        sanction_level=0,
        benefit_amount_cents=41650,
    )
