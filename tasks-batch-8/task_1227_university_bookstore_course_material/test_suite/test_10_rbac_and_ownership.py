"""Role-based access control and entity-backed ownership checks."""
from test_helpers import (
    ApiErrorId,
    create_approved_adoption,
    create_faculty,
    create_publisher_with_agreement,
    create_section,
    create_student,
    create_term,
    create_title,
    get_success_data,
    make_faculty_headers,
    make_student_headers,
    open_section,
    open_term_adoption,
    place_order,
    reset_clock,
    drive_term_to_sales_open,
    set_clock,
    setup_sales_open_with_approved_adoption,
    submit_adoption,
    validate_error,
    validate_success,
)
from test_helpers import MANAGER


def test_faculty_cannot_approve_adoption(api):
    """PRD §2.1: "If the role is recognized but is not permitted on the target
    endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "BookstoreManager — operates the store day to day: reviews and
    approves adoptions, edits and commits buy plans, locks sections, advances
    the term through its operational phases, processes returns with override
    authority, refunds inclusive-access charges, and pays or rejects buyback
    tickets."

    Design: Corner/roles/faculty_cannot_approve_adoption
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000001016", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    from test_helpers import create_adoption
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    submit_adoption(adoption["id"], faculty["id"])
    validate_success(api.start_review_adoption(adoption["id"], MANAGER))

    # Even the owning faculty member cannot run the manager-only approve.
    resp = api.approve_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = get_success_data(
        api.get_adoption(adoption["id"], make_faculty_headers(faculty["id"]))
    )
    assert current["status"] == "UNDER_REVIEW"


def test_student_cannot_read_others_order_returns_not_owner(api):
    """PRD §2.1: "Where an endpoint is owner-scoped and the acting entity does
    not own the target resource, the rejection is `ERR_NOT_OWNER` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the
    acting `Student` record; ownership checks compare the resource's
    `student_id` field to `X-User-ID`."

    Design: Corner/roles/student_cannot_read_others_order_returns_not_owner
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "has_used": False,
                         "has_rental": False, "has_digital": False},
        isbn="9780000001017",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1}],
    )
    other = create_student(full_name="Stu Two", email="stu2@uni.edu")

    resp = api.get_order(order["id"], make_student_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
