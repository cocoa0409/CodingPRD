"""Reference resolution: thirteen existence roots, a three-root write, and two link fabrics.

Each unknown identifier must be reported with its own error id rather than a shared generic
404, the work-order write must resolve its three parents in the declared rank order, and the
two non-tree links -- vendor to certification and obligation to obligation -- must behave
like the fabrics the PRD describes.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_COMPLIANCE_OBLIGATION_NOT_FOUND,
    ERR_DUPLICATE_CERTIFICATION,
    ERR_HOME_NOT_FOUND,
    ERR_LEASE_NOT_FOUND,
    ERR_MARKET_NOT_FOUND,
    ERR_PROSPECT_NOT_FOUND,
    ERR_RENOVATION_PROJECT_NOT_FOUND,
    ERR_RENTAL_APPLICATION_NOT_FOUND,
    ERR_SCOPE_TEMPLATE_NOT_FOUND,
    ERR_SHOWING_SLOT_NOT_FOUND,
    ERR_UNDERWRITING_CASE_NOT_FOUND,
    ERR_VENDOR_CERTIFICATION_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_ids,
    assert_page_meta,
    created,
    failed,
    page,
)
from test_helpers.constants import ABSENT_UUID, CLOCK_AUG_01, OBLIGATION_OPEN


def test_unknown_catalogue_and_acquisition_ids_each_get_their_own_404(api):
    """Four roots, four distinct error ids -- a shared 404 handler fails three of them.

    PRD SS2.7 ranks the existence checks one root at a time: "**Rank 50 -- unknown market.** A
    `marketId` in the path or a `market_id` in the payload that identifies no stored market.
    `ERR_MARKET_NOT_FOUND` (404)"; "**Rank 52 -- unknown scope template.** A `scopeTemplateId`
    in the path ... `ERR_SCOPE_TEMPLATE_NOT_FOUND` (404)"; "**Rank 54 -- unknown home.**
    `ERR_HOME_NOT_FOUND` (404), on every endpoint carrying `homeId` in the path or `home_id` in
    the payload"; "**Rank 56 -- unknown underwriting case.** A `caseId` in the path that
    identifies no stored case. `ERR_UNDERWRITING_CASE_NOT_FOUND` (404)".

    Design: Corner/entities/unknown_catalog_and_acquisition_ids_not_found_404
    """
    x.set_clock(api, CLOCK_AUG_01)

    failed(api.get_market(ABSENT_UUID, x.ADMIN), ERR_MARKET_NOT_FOUND)
    failed(api.get_scope_template(ABSENT_UUID, x.ADMIN), ERR_SCOPE_TEMPLATE_NOT_FOUND)
    failed(api.get_home(ABSENT_UUID, x.ADMIN), ERR_HOME_NOT_FOUND)
    failed(
        api.get_underwriting_case(ABSENT_UUID, x.ANALYST), ERR_UNDERWRITING_CASE_NOT_FOUND
    )


def test_unknown_vendor_and_renovation_ids_each_get_their_own_404(api):
    """The vendor-network and renovation roots keep their own identities too.

    PRD SS2.7: "**Rank 58 -- unknown vendor.** A `vendorId` in the path, or a `vendor_id` in
    the payload, that identifies no stored vendor. `ERR_VENDOR_NOT_FOUND` (404)"; "**Rank 60 --
    unknown certification.** A `certificationId` in the path that identifies no stored
    certification. `ERR_VENDOR_CERTIFICATION_NOT_FOUND` (404)"; "**Rank 62 -- unknown
    renovation project.** A `projectId` in the path, or a `project_id` in the payload, that
    identifies no stored project. `ERR_RENOVATION_PROJECT_NOT_FOUND` (404)"; "**Rank 64 --
    unknown work order.** `ERR_WORK_ORDER_NOT_FOUND` (404), on every endpoint carrying
    `workOrderId` in the path or `work_order_id` in the payload."

    Design: Corner/entities/unknown_vendor_and_project_ids_not_found_404
    """
    x.set_clock(api, CLOCK_AUG_01)

    failed(api.get_vendor(ABSENT_UUID, x.VENDOR_MANAGER), ERR_VENDOR_NOT_FOUND)
    failed(
        api.get_vendor_certification(ABSENT_UUID, x.VENDOR_MANAGER),
        ERR_VENDOR_CERTIFICATION_NOT_FOUND,
    )
    failed(
        api.get_renovation_project(ABSENT_UUID, x.OPS), ERR_RENOVATION_PROJECT_NOT_FOUND
    )
    failed(api.get_work_order(ABSENT_UUID, x.OPS), ERR_WORK_ORDER_NOT_FOUND)


def test_unknown_leasing_and_compliance_ids_each_get_their_own_404(api):
    """The five leasing and compliance roots complete the existence layer.

    PRD SS2.7: "**Rank 66 -- unknown prospect.** ... `ERR_PROSPECT_NOT_FOUND` (404)"; "**Rank
    68 -- unknown showing slot.** A `slotId` in the path that identifies no stored slot.
    `ERR_SHOWING_SLOT_NOT_FOUND` (404)"; "**Rank 70 -- unknown rental application.** An
    `applicationId` in the path, or an `application_id` in the payload, that identifies no
    stored application. `ERR_RENTAL_APPLICATION_NOT_FOUND` (404)"; "**Rank 72 -- unknown
    lease.** `ERR_LEASE_NOT_FOUND` (404), on the single-lease read, execute, void and deposit
    payment"; "**Rank 74 -- unknown compliance obligation.** ...
    `ERR_COMPLIANCE_OBLIGATION_NOT_FOUND` (404)."

    Design: Corner/entities/unknown_leasing_and_compliance_ids_not_found_404
    """
    x.set_clock(api, CLOCK_AUG_01)

    failed(api.get_prospect(ABSENT_UUID, x.AGENT), ERR_PROSPECT_NOT_FOUND)
    failed(api.get_showing_slot(ABSENT_UUID, x.AGENT), ERR_SHOWING_SLOT_NOT_FOUND)
    failed(
        api.get_rental_application(ABSENT_UUID, x.AGENT), ERR_RENTAL_APPLICATION_NOT_FOUND
    )
    failed(api.get_lease(ABSENT_UUID, x.AGENT), ERR_LEASE_NOT_FOUND)
    failed(
        api.get_compliance_obligation(ABSENT_UUID, x.COMPLIANCE),
        ERR_COMPLIANCE_OBLIGATION_NOT_FOUND,
    )


def test_work_order_creation_resolves_its_three_parents_in_rank_order(api):
    """Template beats home, home beats project, and a project-less payload still creates.

    PRD SS3.3: "Each names the property through `home_id` and the standardized scope through
    `scope_template_id` ... `project_id` is optional: standalone resident-maintenance work that
    is not part of any project leaves it as the empty string, and a `project_id` that names no
    stored project is refused with `ERR_RENOVATION_PROJECT_NOT_FOUND`."  PRD SS2.7 fixes which
    of the three is reported when more than one is unresolvable, since "**Evaluation stops at
    the first violated rule, and only that rule's error is reported**" and the three roots sit
    at rank 52 (`ERR_SCOPE_TEMPLATE_NOT_FOUND`, which "Applies to ... work-order creation"),
    rank 54 (`ERR_HOME_NOT_FOUND`) and rank 62 (`ERR_RENOVATION_PROJECT_NOT_FOUND`, which
    applies to "work-order creation").

    Design: Corner/entities/work_order_resolves_three_independent_roots_before_create
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    def order(home_id, template_id, **overrides):
        return f.work_order_payload(
            home_id,
            template_id,
            work_type="RESIDENT_MAINTENANCE",
            crew_size=2,
            scheduled_end_date="2026-08-11",
            **overrides
        )

    failed(
        api.create_work_order(order(home["id"], ABSENT_UUID), x.OPS),
        ERR_SCOPE_TEMPLATE_NOT_FOUND,
    )
    failed(
        api.create_work_order(order(ABSENT_UUID, paint["id"]), x.OPS), ERR_HOME_NOT_FOUND
    )
    failed(
        api.create_work_order(order(ABSENT_UUID, ABSENT_UUID), x.OPS),
        ERR_SCOPE_TEMPLATE_NOT_FOUND,
    )
    failed(
        api.create_work_order(
            order(home["id"], paint["id"], project_id=ABSENT_UUID), x.OPS
        ),
        ERR_RENOVATION_PROJECT_NOT_FOUND,
    )

    standalone = created(api.create_work_order(order(home["id"], paint["id"]), x.OPS))
    assert_fields(
        standalone, home_id=home["id"], scope_template_id=paint["id"]
    )
    assert_absent_or_empty(standalone, "project_id")


def test_a_vendor_holds_two_trades_but_not_the_same_trade_twice(api):
    """PAINT and HVAC coexist on one vendor; a second active PAINT is a 409.

    PRD SS3.4: "A certification is created with `status` `ACTIVE`, and a vendor may not hold two
    active certifications for the same `certification_code` -- a second attempt is refused with
    `ERR_DUPLICATE_CERTIFICATION`. ... Certifications are readable individually and as a list
    filterable by `vendor_id`, `certification_code` and `status`."

    Design: Corner/entities/vendor_holds_many_certifications_and_rejects_duplicate_codes
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    vendor = x.create_vendor(api, market["id"])

    paint_cert = created(
        api.create_vendor_certification(
            f.vendor_certification_payload(vendor["id"], "PAINT", expires_on="2027-01-31"),
            x.VENDOR_MANAGER,
        )
    )
    hvac_cert = created(
        api.create_vendor_certification(
            f.vendor_certification_payload(vendor["id"], "HVAC", expires_on="2027-01-31"),
            x.VENDOR_MANAGER,
        )
    )
    assert_fields(paint_cert, certification_code="PAINT", vendor_id=vendor["id"])
    assert_fields(hvac_cert, certification_code="HVAC", vendor_id=vendor["id"])

    failed(
        api.create_vendor_certification(
            f.vendor_certification_payload(
                vendor["id"], "PAINT", effective_on="2026-02-01", expires_on="2027-02-28"
            ),
            x.VENDOR_MANAGER,
        ),
        ERR_DUPLICATE_CERTIFICATION,
    )

    rows, meta = page(
        api.list_vendor_certifications(x.VENDOR_MANAGER, {"vendor_id": vendor["id"]})
    )
    assert_page_meta(meta, total_count=2)
    assert_ids(rows, [paint_cert["id"], hvac_cert["id"]])
    for row in rows:
        assert_fields(row, vendor_id=vendor["id"])


def test_an_obligation_may_supersede_another_but_not_a_missing_one(api):
    """The renewal stores the prior id, the filter finds it, and a dangling id is a 404.

    PRD SS3.9: "`supersedes_obligation_id` optionally names the prior-cycle obligation this one
    renews and is the empty string on a first cycle. The obligation is created in `OPEN` with
    `resolution_round` 0 ... Obligations are readable individually ... and as a list filterable
    by `home_id`, `supersedes_obligation_id`, `work_order_id`, `obligation_type`, `severity`
    and `status`."  PRD SS2.7 rank 74: "An `obligationId` in the path, or a
    `supersedes_obligation_id` in the payload, that identifies no stored obligation.
    `ERR_COMPLIANCE_OBLIGATION_NOT_FOUND` (404). Applies to the single-obligation read, plan,
    submit-resolution, review-resolution and obligation creation."

    Design: Corner/entities/compliance_obligation_supersedes_chain_is_self_referential
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    first = x.open_obligation(api, home["id"])

    renewal = created(
        api.create_compliance_obligation(
            f.obligation_payload(
                home["id"],
                description="Mailbox paint peeling - reissued notice",
                due_on="2027-01-31",
                supersedes_obligation_id=first["id"],
            ),
            x.COMPLIANCE,
        )
    )
    assert_fields(
        renewal,
        supersedes_obligation_id=first["id"],
        status=OBLIGATION_OPEN,
        resolution_round=0,
    )
    assert_absent_or_empty(first, "supersedes_obligation_id")

    rows, meta = page(
        api.list_compliance_obligations(
            x.COMPLIANCE, {"supersedes_obligation_id": first["id"]}
        )
    )
    assert_page_meta(meta, total_count=1)
    assert_ids(rows, [renewal["id"]])

    failed(
        api.create_compliance_obligation(
            f.obligation_payload(
                home["id"],
                description="Dangling supersede",
                due_on="2027-01-31",
                supersedes_obligation_id=ABSENT_UUID,
            ),
            x.COMPLIANCE,
        ),
        ERR_COMPLIANCE_OBLIGATION_NOT_FOUND,
    )
