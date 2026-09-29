"""
Identity gates: five peer roles with no hierarchy, two entity-backed roles scoped to
their own rows, and one adjudication that structurally needs two distinct people.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_axes, assert_cents
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
    AUDITOR_3_HEADERS,
    NO_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    headers_missing_role,
    make_customer_contact_headers,
    make_technician_headers,
)
from test_helpers.types import (
    BASIS_AS_CALIBRATED,
    CASE_PENDING_REVIEW,
    CASE_SUBSTANTIATED,
    CLASS_THEFT_SUSPECT,
    DECISION_SUBSTANTIATE,
    DISPENSER_ACTIVE,
    PLACEMENT_INSTALLED,
    REMEDIATION_CHARGEBACK,
    REVIEW_CLOSED,
    SYMPTOM_LEAK,
    VISIT_SCHEDULED,
)


def test_five_peer_roles_cannot_borrow_each_others_exclusive_writes(api):
    """
    The roles are peers with no hierarchy, and each exclusive write is closed to every
    other role: the commercial role cannot stock the catalogue or fit a feed, the auditor
    cannot dispatch, the engineer cannot escalate, the customer cannot open accounts and
    the platform role cannot order equipment back. Every refusal is the role error rather
    than a payload or state error, and the shared read both field roles are granted still
    succeeds on the same fixture.

    PRD §2.2: "Once the headers are read, the declared role must appear among the roles
    the addressed endpoint permits; a role that does not is rejected with
    `ERR_FORBIDDEN_ROLE`, and that check runs **before** the request body is parsed, so
    a forbidden role that also sends a malformed body still sees the role error rather
    than a shape error."

    Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    ticket = X.file_ticket(api, base, placement["id"])
    review = X.draft_review(api, base)

    validate_error(
        api.create_chemical_product(
            F.detergent_payload(sku="DET-999"), ACCOUNT_MANAGER_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], base["detergent_id"]),
            ACCOUNT_MANAGER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.dispatch_service_ticket(
            ticket["id"], AUDITOR_1_HEADERS, F.dispatch_payload()
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_investigation_case(
            F.investigation_case_payload(review["id"]), base["technician_headers"]
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_customer(
            F.customer_payload(name="Rogue Account"), base["customer_headers"]
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_retrieval_order(placement["id"], PLATFORM_ADMIN_HEADERS),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    shared = get_success_data(
        api.get_site(base["site_id"], base["technician_headers"])
    )
    assert shared["id"] == base["site_id"]

    assert_axes(
        get_success_data(
            api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
        ),
        placement_status=PLACEMENT_INSTALLED,
    )


def test_identity_is_checked_before_anything_else_except_on_the_clock(api):
    """
    Authentication runs ahead of authorisation and ahead of routing: with the role header
    absent, the very read and write that succeed for a valid caller answer unauthenticated
    rather than forbidden or not-found. The one declared exemption, the clock hook, still
    works with no headers at all.

    PRD §2.2: "Either header missing or present but empty is rejected with
    `ERR_UNAUTHENTICATED` before any other check runs. The single exception is the
    logical-clock endpoint, which is a test-driving hook and requires no headers at all."

    Design: Corner/rbac/missing_identity_headers_are_unauthenticated_except_on_the_clock
    """
    customer = X.create_customer(api)

    validate_error(
        api.get_customer(customer["id"], NO_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.create_customer(
            F.customer_payload(name="Anonymous Account"), headers_missing_role("am-1")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    clock = get_success_data(
        api.set_clock(F.clock_payload("2026-08-02T00:00:00Z"), NO_HEADERS)
    )
    assert clock["current_utc"] == "2026-08-02T00:00:00Z"


def test_both_entity_backed_roles_are_scoped_to_their_own_row(api):
    """
    Both entity-backed roles clear the role gate and fail the ownership gate: the other
    account's contact may neither read this account's kitchen nor file work against its
    machine, and an engineer may not book a visit in a colleague's name — that ownership
    refusal arrives before the check that the job was even dispatched to the colleague.
    The owning contact reads the same row, and the assigned engineer books the identical
    window that was refused.

    PRD §2.8: "**Ownership scope** — a `CustomerContact` may only address its own
    account's resources and a `ServiceTechnician` may only act as itself, otherwise
    `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/entity_backed_roles_are_scoped_to_their_own_row
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    ticket = X.dispatched_ticket(api, base, placement["id"])
    assert ticket["assigned_technician_id"] == base["technician_id"]

    other_customer = X.create_customer(api, name="Quayside Canteen Group")
    X.create_site(api, other_customer["id"], name="Quayside Canteen Line")
    other_contact = make_customer_contact_headers(other_customer["id"])

    other_engineer = X.create_technician(api, name="Nils Brandt", region_code="NW")
    other_engineer_headers = make_technician_headers(other_engineer["id"])

    validate_error(
        api.get_site(base["site_id"], other_contact), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.create_service_ticket(
            F.service_ticket_payload(placement["id"], SYMPTOM_LEAK), other_contact
        ),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    booking = F.service_visit_payload(
        ticket["id"],
        base["technician_id"],
        scheduled_start_at="2026-08-01T11:00:00Z",
        scheduled_end_at="2026-08-01T12:00:00Z",
    )
    validate_error(
        api.create_service_visit(booking, other_engineer_headers),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )

    own = get_success_data(api.get_site(base["site_id"], base["customer_headers"]))
    assert own["id"] == base["site_id"]

    booked = validate_success(
        api.create_service_visit(booking, base["technician_headers"]), 201
    )
    assert booked["visit_status"] == VISIT_SCHEDULED


def test_turning_a_variance_into_money_needs_a_third_pair_of_eyes(api):
    """
    Two distinct identities are structurally required to convert a variance into a
    charge: the auditor who both published the finding and opened the case is refused her
    own adjudication even though her role, the case status and the evidence count are all
    in order, and the refusal writes nothing. A second auditor runs the identical call and
    the charge lands on whole containers at list price, closing the review while leaving
    the feed alone, because only a replacement remediation locks feeds.

    PRD §3.8: "Deciding a case requires `case_status` `PENDING_REVIEW`, else
    `ERR_CASE_NOT_IN_REVIEW`, and requires an auditor who is neither the case's
    `opened_by_user_id` nor the `published_by_user_id` of the review the case was opened
    against, else `ERR_SEGREGATION_OF_DUTIES` — converting a variance into a chargeback
    therefore takes two independent auditors beyond the one who drafted the review."

    PRD §3.8: "Link 3 is conditional on the remediation actually ordered: only when
    `remediation` is `DISPENSER_REPLACEMENT` does every dispenser of the review's site
    metering the review's `product_id` whose `dispenser_status` is `ACTIVE` become
    `LOCKED_OUT` with `lockout_reason` `INVESTIGATION_HOLD`, processed in dispenser
    `created_at` ascending order."

    Design: Corner/rbac/the_auditor_who_published_the_variance_cannot_adjudicate_its_case
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.set_clock(api, "2026-08-02T00:00:00Z")
    X.record_delivery(api, base, unit_count=1, delivered_at="2026-08-02T00:00:00Z")
    X.ingest_reading(api, placement["id"], "2026-08-02T00:00:00Z", 100)

    review = X.draft_review(
        api,
        base,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-08T00:00:00Z",
        basis=BASIS_AS_CALIBRATED,
        opening_inventory_ml=20000,
        ending_inventory_ml=0,
        auditor_headers=AUDITOR_3_HEADERS,
    )
    assert review["expected_consumption_ml"] == 800
    assert review["actual_consumption_ml"] == 40000
    assert review["classification"] == CLASS_THEFT_SUSPECT

    published = X.publish_review(api, review["id"], auditor_headers=AUDITOR_1_HEADERS)
    assert published["published_by_user_id"] == "auditor-1"

    case = X.open_case(api, review["id"], auditor_headers=AUDITOR_1_HEADERS)
    assert case["opened_by_user_id"] == "auditor-1"
    staged = X.submit_case(
        api,
        case["id"],
        ["DELIVERY_LOG", "INVENTORY_COUNT"],
        auditor_headers=AUDITOR_1_HEADERS,
    )
    assert staged["case_status"] == CASE_PENDING_REVIEW
    assert staged["evidence_item_count"] == 2

    validate_error(
        api.review_investigation_case(
            case["id"],
            F.case_review_payload(
                DECISION_SUBSTANTIATE,
                remediation=REMEDIATION_CHARGEBACK,
                finding_note="Self-adjudication attempt",
            ),
            AUDITOR_1_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    unchanged = get_success_data(
        api.get_investigation_case(case["id"], AUDITOR_2_HEADERS)
    )
    assert unchanged["case_status"] == CASE_PENDING_REVIEW
    assert_cents(unchanged["chargeback_cents"], 0)

    adjudicated = X.review_case(
        api,
        case["id"],
        DECISION_SUBSTANTIATE,
        remediation=REMEDIATION_CHARGEBACK,
        finding_note="Two containers unaccounted for",
        auditor_headers=AUDITOR_2_HEADERS,
    )
    assert adjudicated["case_status"] == CASE_SUBSTANTIATED
    # 39200 ml of excess rounds up to 2 whole 20000 ml containers at the 9600 list price.
    assert_cents(adjudicated["chargeback_cents"], 19200)
    assert adjudicated["reviewed_by_user_id"] == "auditor-2"

    assert (
        get_success_data(
            api.get_usage_variance_review(review["id"], AUDITOR_2_HEADERS)
        )["status"]
        == REVIEW_CLOSED
    )
    assert (
        get_success_data(
            api.get_dispenser(dispenser["id"], base["technician_headers"])
        )["dispenser_status"]
        == DISPENSER_ACTIVE
    )
