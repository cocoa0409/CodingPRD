"""Company registration and signatory-application lifecycle tests (PRD §3.1)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def test_company_created_pending_with_null_signatory_since(api):
    """PRD §3.1: "The company is created with status `PENDING` and `version` 1,
    and the `id` in the response becomes the caller's `X-User-ID` for all
    subsequent `ProducerRep` calls."
    PRD §3.1: "While `PENDING`, the company's `signatory_since` is null."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/producer_company_create_defaults_and_system_fields
    """
    company = th.register_company("Aster Films LLC", "20-0000001")
    data = th.validate_success(
        api.get_producer_company(company["id"], th.owner_headers(company))
    )
    th.assert_producer_company(data)
    assert data["status"] == "PENDING"
    assert data.get("signatory_since") is None
    assert data["version"] == 1


def test_application_created_draft_with_zero_review_rounds(api):
    """PRD §3.1: "The application starts in `DRAFT`."
    PRD §3.1: "each such request consumes one of at most 3 review rounds,
    recorded in `review_rounds`, and a request made when `review_rounds` has
    already reached 3 is rejected with `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 422)."
    (Three consumed rounds must reach exactly 3, so a fresh application starts
    at 0; no denial has been recorded on a new application.)

    Design: Corner/entities/signatory_application_defaults_on_create
    """
    company = th.register_company("Bracken LLC", "20-0000002")
    data = th.validate_success(
        api.create_signatory_application(
            th.create_signatory_application_payload(
                producer_company_id=company["id"],
                requested_agreement_scope="TELEVISION",
                estimated_slate_budget_cents=9_000_000,
            ),
            th.owner_headers(company),
        ),
        expected_status=201,
    )
    th.assert_signatory_application(data)
    assert data["status"] == "DRAFT"
    assert data["review_rounds"] == 0
    assert data.get("denial_reason") is None


def test_submit_from_under_review_rejected(api):
    """PRD §3.1: "Submitting it — allowed whether the company is `PENDING`,
    `SIGNATORY`, or `SUSPENDED` — moves it to `UNDER_REVIEW`; submitting from
    any other state is rejected with `ERR_APPLICATION_STATE` (HTTP 409)."

    Design: Corner/state_machines/signatory_application_submit_twice_rejected
    """
    company = th.register_company("Hollyhock LLC", "20-0000008")
    application = th.create_application(company, scope="NEW_MEDIA", slate=9_000_000)
    th.submit_application(application, company)

    resp = api.submit_application(application["id"], {}, th.owner_headers(company))
    th.validate_error(resp, E.ERR_APPLICATION_STATE)

    apps, _ = th.validate_paginated(
        api.list_company_applications(company["id"], th.owner_headers(company))
    )
    current = next(a for a in apps if a["id"] == application["id"])
    assert current["status"] == "UNDER_REVIEW", "second submit must not change state"


def test_fourth_info_request_rejected_after_three_rounds(api, union_rep_headers):
    """PRD §3.1: "A `UnionRep` may push the application from `UNDER_REVIEW` to
    `INFO_REQUESTED`, attaching an `info_request_note`; each such request
    consumes one of at most 3 review rounds, recorded in `review_rounds`, and a
    request made when `review_rounds` has already reached 3 is rejected with
    `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 422)."

    Design: Corner/validations/review_rounds_exhausted_on_fourth_request
    """
    company = th.register_company("Navelwort LLC", "20-0000041")
    application = th.create_application(company, slate=9_000_000)
    th.submit_application(application, company)
    for round_no in (1, 2, 3):
        th.get_success_data(api.request_info(
            application["id"], {"info_request_note": f"round {round_no}"},
            union_rep_headers,
        ))
        th.get_success_data(api.provide_info(
            application["id"], {"info_response": f"answer {round_no}"},
            th.owner_headers(company),
        ))

    resp = api.request_info(
        application["id"], {"info_request_note": "round 4"}, union_rep_headers,
    )
    th.validate_error(resp, E.ERR_REVIEW_ROUNDS_EXHAUSTED)

    apps, _ = th.validate_paginated(
        api.list_company_applications(company["id"], th.owner_headers(company))
    )
    current = next(a for a in apps if a["id"] == application["id"])
    assert current["review_rounds"] == 3
    assert current["status"] == "UNDER_REVIEW", "exhausted request must not change state"


def test_info_request_cycle_increments_review_rounds(api, union_rep_headers):
    """PRD §3.1: "each such request consumes one of at most 3 review rounds,
    recorded in `review_rounds`". PRD §3.1: "The producer answers by providing
    an `info_response`, which returns the application from `INFO_REQUESTED` to
    `UNDER_REVIEW` for another look."
    The UNDER_REVIEW -> INFO_REQUESTED -> UNDER_REVIEW loop is exercised twice.

    Design: Difficulty/non_linear_state_machine/application_info_request_cycle
    """
    company = th.register_company("Foxglove Films LLC", "44-3333333")
    application = th.create_application(company, slate=60_000_000)
    th.submit_application(application, company)

    for note, answer in (("Provide financing plan", "Financing plan v1 attached"),
                         ("Provide chain of title", "Chain of title attached")):
        app_data = th.get_success_data(api.request_info(
            application["id"], {"info_request_note": note}, union_rep_headers,
        ))
        assert app_data["status"] == "INFO_REQUESTED"
        app_data = th.get_success_data(api.provide_info(
            application["id"], {"info_response": answer}, th.owner_headers(company),
        ))
        assert app_data["status"] == "UNDER_REVIEW"

    apps, _ = th.validate_paginated(
        api.list_company_applications(company["id"], th.owner_headers(company))
    )
    current = next(a for a in apps if a["id"] == application["id"])
    assert current["review_rounds"] == 2


def test_application_approved_after_cycles_makes_company_signatory(api, union_rep_headers):
    """PRD §3.1: "Approval moves the application to `APPROVED`; if the company
    is still `PENDING`, the company transitions to `SIGNATORY` and
    `signatory_since` is stamped from the logical clock".
    PRD §2.5: "The clock's startup default, before any client call, is exactly
    `2026-08-01T00:00:00Z`".

    Design: Difficulty/non_linear_state_machine/application_info_request_cycle
    """
    company = th.register_company("Foxglove Films LLC", "44-3333333")
    application = th.create_application(company, slate=60_000_000)
    th.submit_application(application, company)
    for round_no in (1, 2):
        th.get_success_data(api.request_info(
            application["id"], {"info_request_note": f"round {round_no}"},
            union_rep_headers,
        ))
        th.get_success_data(api.provide_info(
            application["id"], {"info_response": f"answer {round_no}"},
            th.owner_headers(company),
        ))

    decided = th.get_success_data(api.decide_application(
        application["id"], {"decision": "APPROVE"}, union_rep_headers,
    ))
    assert decided["status"] == "APPROVED"
    assert decided["review_rounds"] == 2

    company_data = th.validate_success(
        api.get_producer_company(company["id"], th.owner_headers(company))
    )
    assert company_data["status"] == "SIGNATORY"
    assert company_data["signatory_since"] is not None
    assert company_data["signatory_since"].startswith("2026-08-01"), (
        "signatory_since is stamped from the logical clock (default 2026-08-01)"
    )


def test_producer_rep_cannot_request_info(api):
    """PRD §2.1: "A request whose role is authenticated but not on the target
    endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §3.1: "A `UnionRep` may push the application from `UNDER_REVIEW` to
    `INFO_REQUESTED`, attaching an `info_request_note`."

    Design: Corner/rbac/producerrep_cannot_request_info
    """
    company = th.register_company("Toadflax LLC", "20-0000047")
    application = th.create_application(company, scope="NEW_MEDIA", slate=9_000_000)
    th.submit_application(application, company)

    resp = api.request_info(
        application["id"], {"info_request_note": "self request"},
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_UNAUTHORIZED_ROLE)

    apps, _ = th.validate_paginated(
        api.list_company_applications(company["id"], th.owner_headers(company))
    )
    current = next(a for a in apps if a["id"] == application["id"])
    assert current["review_rounds"] == 0, "denied request must have no side effect"
