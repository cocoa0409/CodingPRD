"""Role, identity and state-scope corners of the adoption review contract.

Four distinct guards live on the authentication and authorization path: the two
identity headers themselves, the endpoint's permitted-role list, the officer's
binding to one single state, and the two segregation-of-duties comparisons that
look past the role at the acting user identifier. Each test here refuses one
call and then proves the very same call succeeds once the only thing that
changed is who is making it.
"""

import pytest

from test_helpers import (
    ADOPTION_MODEL_OPEN_TERRITORY,
    CYCLE_STATUS_OPEN,
    CYCLE_STATUS_SCHEDULED,
    CONTENT_EDIT_STATUS_APPROVED,
    CONTENT_EDIT_STATUS_PROPOSED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_QUOTED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_FILED,
    ApiErrorId,
    assert_print_unit_ledger_balances,
    build_user_headers,
    factories,
    is_valid_uuid,
    make_editorial_director_headers,
    make_platform_admin_headers,
    make_publisher_editor_headers,
    make_sales_rep_headers,
    make_state_adoption_officer_headers,
    make_unauthenticated_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    propose_content_edit,
    seed_cycle,
    seed_draft_submission,
    seed_open_cycle,
    seed_state,
    seed_title,
    set_clock,
)


def test_sales_rep_cannot_file_a_submission(api, sales_rep_headers, publisher_editor_headers):
    """PRD 2.1: "If both headers are well formed but the declared role is not among the roles the addressed endpoint permits, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Filing with the state is the publisher editor's act, so the field sales
    representative is turned away on the role check alone. Nothing about the
    draft changes: the editor repeats the identical call and it files.

    Design: Corner/rbac/sales_rep_cannot_file_a_submission
    """
    world = seed_open_cycle(api, "VT", subject="ELA", grade=6)
    submission_id = seed_draft_submission(api, world)

    refused = api.file_submission(submission_id, sales_rep_headers)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    still_draft = validate_success(api.get_submission(submission_id, publisher_editor_headers))
    assert still_draft["review_status"] == REVIEW_STATUS_DRAFT

    filed = validate_success(api.file_submission(submission_id, publisher_editor_headers))
    assert filed["review_status"] == REVIEW_STATUS_FILED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 1


def test_a_request_without_role_headers_is_unauthenticated(api, platform_admin_headers):
    """PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. If either header is absent, or if `X-User-Role` is not one of the eight roles named below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    The very first write against an empty platform is refused twice — once for
    absent identity headers, once for a role string outside the eight the
    contract declares — and then accepted from the platform administrator.

    Design: Corner/rbac/a_request_without_role_headers_is_unauthenticated
    """
    payload = factories.state_profile_payload(
        "AK", adoption_model=ADOPTION_MODEL_OPEN_TERRITORY
    )

    headerless = api.create_state_profile(payload, make_unauthenticated_headers())
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    undeclared_role = api.create_state_profile(
        payload, build_user_headers("who-1", "SuperUser")
    )
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    created = validate_success(
        api.create_state_profile(payload, platform_admin_headers), expected_status=201
    )
    assert is_valid_uuid(created["id"])

    read_back = validate_success(
        api.get_state_profile(created["id"], platform_admin_headers)
    )
    assert read_back["state_code"] == "AK"


def test_the_same_user_cannot_review_the_content_edit_it_proposed(api):
    """PRD 2.1: "Reviewing a content edit requires an `X-User-ID` different from that edit's `proposed_by_user_id`; confirming a district order requires an `X-User-ID` different from that order's `created_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 3.3: "Both verdicts require an acting `X-User-ID` different from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    The person who proposed the adaptation cannot bless it, even when they are
    acting in the approving capacity: the comparison is on the user identifier,
    not the role. A second director approves the very same edit, and because
    approval is not application the edition is untouched.

    Design: Corner/rbac/the_same_user_cannot_review_the_content_edit_it_proposed
    """
    world = seed_state(api, "IN", required_topics=["INDIANA_WATERSHEDS"])
    title_id = seed_title(
        api,
        world,
        subject="SCIENCE",
        grade_low=7,
        grade_high=7,
        content_tags=["LAB_SAFETY"],
        page_count=300,
        signature_page_capacity=384,
    )
    edit_id = propose_content_edit(
        api,
        world,
        topic_code="INDIANA_WATERSHEDS",
        pages_delta=6,
        proposer=make_publisher_editor_headers("u-7"),
    )

    self_review = api.review_content_edit(
        edit_id, {"verdict": "APPROVE"}, make_editorial_director_headers("u-7")
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    unchanged = validate_success(
        api.get_content_edit(edit_id, make_editorial_director_headers("u-9"))
    )
    assert unchanged["status"] == CONTENT_EDIT_STATUS_PROPOSED
    assert unchanged["reviewed_by_user_id"] is None

    approved = validate_success(
        api.review_content_edit(
            edit_id, {"verdict": "APPROVE"}, make_editorial_director_headers("u-9")
        )
    )
    assert approved["status"] == CONTENT_EDIT_STATUS_APPROVED
    assert approved["proposed_by_user_id"] == "u-7"
    assert approved["reviewed_by_user_id"] == "u-9"

    title = validate_success(api.get_title(title_id, make_platform_admin_headers()))
    assert title["page_count"] == 300
    assert title["content_revision"] == 1


def test_the_rep_who_quoted_an_order_cannot_confirm_it(api):
    """PRD 3.9: "The confirming rep's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.9: "A confirmation writes `contracted_tcv_cents` and `freight_surcharge_cents` from the contracted variant, records `confirmed_by_user_id`, sets `allocated_units` to `print_units`, and moves the stock: the edition's `on_hand_units` decreases by `print_units` and its `committed_units` increases by the same amount."

    The representative who entered the district quote may not also sign it off.
    The refusal moves no stock at all; the second representative's confirmation
    commits every one of the ten print units.

    Design: Corner/rbac/the_rep_who_quoted_an_order_cannot_confirm_it
    """
    admin = make_platform_admin_headers()
    quoting_rep = make_sales_rep_headers("sr-1")
    confirming_rep = make_sales_rep_headers("sr-2")

    world = seed_state(api, "KY")
    title_id = seed_title(
        api,
        world,
        receipt_units=40,
        subject="MATH",
        grade_low=3,
        grade_high=3,
        content_tags=["FRACTION_MODELS"],
        page_count=280,
        list_price_cents=9000,
    )
    quoted = validate_success(
        api.create_district_order(
            factories.district_order_payload(
                world.state_id,
                title_id,
                print_units=10,
                digital_seats=0,
                district_ref="KY-DIST-4",
            ),
            quoting_rep,
        ),
        expected_status=201,
    )
    order_id = quoted["id"]
    assert quoted["status"] == ORDER_STATUS_QUOTED
    assert quoted["created_by_user_id"] == "sr-1"
    assert quoted["allocated_units"] == 0

    self_confirm = api.confirm_district_order(order_id, quoting_rep)
    validate_error(self_confirm, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    untouched_order = validate_success(api.get_district_order(order_id, admin))
    assert untouched_order["status"] == ORDER_STATUS_QUOTED
    assert untouched_order["allocated_units"] == 0

    untouched_title = validate_success(api.get_title(title_id, admin))
    assert untouched_title["on_hand_units"] == 40
    assert untouched_title["committed_units"] == 0

    confirmed = validate_success(api.confirm_district_order(order_id, confirming_rep))
    assert confirmed["status"] == ORDER_STATUS_CONFIRMED
    assert confirmed["created_by_user_id"] == "sr-1"
    assert confirmed["confirmed_by_user_id"] == "sr-2"
    assert confirmed["allocated_units"] == 10

    title = validate_success(api.get_title(title_id, admin))
    assert title["on_hand_units"] == 30
    assert title["committed_units"] == 10
    assert_print_unit_ledger_balances(title)


def test_an_officer_cannot_advance_another_states_cycle(api, platform_admin_headers):
    """PRD 2.1: "When `X-User-Role` is `StateAdoptionOfficer`, `X-User-ID` is the `id` of the acting `StateProfile`; ownership checks on any resource that references a `StateProfile` compare the resource's state foreign key to `X-User-ID`. Concretely, the officer's own state is compared against `AdoptionCycle.state_id` for a cycle, against the state of the cycle that owns a `CommitteePanel`, a `PresentationSlot` or a `PricingProposal`, and against the path-addressed `StateProfile` when a framework standard is added. Acting outside that state fails with `ERR_STATE_SCOPE_VIOLATION` (HTTP 403)."

    PRD 3.1: "Every successful run increments `phase_epoch` by 1, so the counter records how many advances the cycle has actually taken."

    The neighbouring state's officer cannot walk this state's calendar forward
    even when the clock makes the advance due; the cycle stays SCHEDULED at
    epoch zero until its own officer calls.

    Design: Corner/rbac/an_officer_cannot_advance_another_states_cycle
    """
    wisconsin = seed_state(api, "WI")
    minnesota = seed_state(api, "MN")
    cycle_id = seed_cycle(api, wisconsin, subject="MATH", cycle_year=2027)
    set_clock(api, "2026-09-15T00:00:00Z")

    foreign_officer = make_state_adoption_officer_headers(minnesota.state_id)
    refused = api.advance_cycle_phase(cycle_id, foreign_officer)
    validate_error(refused, ApiErrorId.ERR_STATE_SCOPE_VIOLATION, expected_status=403)

    unchanged = validate_success(
        api.get_adoption_cycle(cycle_id, platform_admin_headers)
    )
    assert unchanged["status"] == CYCLE_STATUS_SCHEDULED
    assert unchanged["phase_epoch"] == 0

    advanced = validate_success(api.advance_cycle_phase(cycle_id, wisconsin.officer))
    assert advanced["status"] == CYCLE_STATUS_OPEN
    assert advanced["phase_epoch"] == 1
    assert advanced["state_id"] == wisconsin.state_id
