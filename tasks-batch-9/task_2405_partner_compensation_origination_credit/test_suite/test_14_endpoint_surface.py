"""Endpoint-surface corners: the contribution record's create/read/list/verify
surface with no update verb, the matter status edges around reopening, and the
peer-review association that needs both of its endpoints to resolve."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    approx2,
    create_assessment,
    create_contribution_record_payload,
    create_cycle,
    create_matter,
    create_partner,
    create_peer_review_payload,
    make_cycle_admin_headers,
    matter_allocations,
    matter_status_payload,
    read_assessment,
    read_partner,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_cycle_admin_headers()


def test_contribution_record_create_read_list_with_no_update_surface(api):
    """PRD 3.3: "Creation returns 201 Created, sets `standard_value_cents` to
    `hours` multiplied by `standard_rate_cents` rounded half up for billable rows
    and to 0 for non-billable rows, and leaves `verified` false with
    `verified_at` null."

    Design: Corner/endpoints/contribution_record_create_read_list_with_no_update_surface
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Nora Nonbill", compensation_model="FORMULA")

    created = validate_success(
        api.create_contribution_record(
            create_contribution_record_payload(
                partner_id=partner["id"],
                cycle_id=cycle["id"],
                kind="NON_BILLABLE",
                category="FIRM_MANAGEMENT",
                hours=40.00,
                standard_rate_cents=0,
                service_period_start="2026-02-01",
                service_period_end="2026-02-28",
            ),
            ADMIN,
        ),
        201,
    )
    assert created["kind"] == "NON_BILLABLE"
    assert created["matter_id"] is None
    assert created["standard_value_cents"] == 0
    assert created["verified"] is False
    assert created["verified_at"] is None
    assert created["version"] == 1

    read_back = validate_success(api.get_contribution_record(created["id"], ADMIN), 200)
    assert read_back["id"] == created["id"]
    assert read_back["hours"] == approx2(40.00)
    assert read_back["category"] == "FIRM_MANAGEMENT"
    assert read_back["version"] == created["version"]

    matching, meta = validate_paginated(
        api.list_contribution_records(
            ADMIN, {"partner_id": partner["id"], "kind": "NON_BILLABLE"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in matching] == [created["id"]]
    _billable, billable_meta = validate_paginated(
        api.list_contribution_records(ADMIN, {"kind": "BILLABLE"})
    )
    assert billable_meta["total_count"] == 0

    # The only mutation the surface offers is verification.
    verified = validate_success(api.verify_contribution_record(created["id"], {}, ADMIN), 200)
    assert verified["verified"] is True
    assert verified["verified_at"] is not None
    assert verified["version"] == created["version"] + 1

    # 40.00 hours weighted 1.50 gives a base of 60, which the pro-bono floor
    # then multiplies by 0.90 because no pro bono hours were booked.
    assert read_partner(api, partner["id"])["non_billable_points"] == approx2(54.00)


def test_matter_reopen_is_allowed_only_from_closed(api):
    """PRD 3.2: "All three edges require the matter to be in the state the edge
    starts from and otherwise report `ERR_MATTER_NOT_OPEN`, and `WRITTEN_OFF` is
    terminal."

    Design: Corner/endpoints/matter_reopen_is_allowed_only_from_closed
    """
    partner = create_partner(api, full_name="Rhea Open")
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-RO",
        client_display_name="Reopen Resources",
        matter_type="NEW_CLIENT",
        opened_on="2026-01-20",
    )
    assert matter["state"] == "OPEN"
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 1

    # Reopening starts from CLOSED, so it is unavailable while the matter is OPEN.
    too_early = api.set_matter_status(matter["id"], matter_status_payload("OPEN"), ADMIN)
    validate_error(too_early, ApiErrorId.ERR_MATTER_NOT_OPEN.value, 409)

    closed = validate_success(
        api.set_matter_status(matter["id"], matter_status_payload("CLOSED"), ADMIN), 200
    )
    assert closed["state"] == "CLOSED"
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 0
    assert len(matter_allocations(api, matter["id"], state="ACTIVE")) == 2

    # Closing starts from OPEN, so it is now unavailable in turn.
    again = api.set_matter_status(matter["id"], matter_status_payload("CLOSED"), ADMIN)
    validate_error(again, ApiErrorId.ERR_MATTER_NOT_OPEN.value, 409)

    reopened = validate_success(
        api.set_matter_status(matter["id"], matter_status_payload("OPEN"), ADMIN), 200
    )
    assert reopened["state"] == "OPEN"
    assert reopened["version"] == closed["version"] + 1
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 1
    assert len(matter_allocations(api, matter["id"], state="ACTIVE")) == 2

    written_off = validate_success(
        api.set_matter_status(
            matter["id"],
            matter_status_payload("WRITTEN_OFF", written_off_reason="Client became insolvent."),
            ADMIN,
        ),
        200,
    )
    assert written_off["state"] == "WRITTEN_OFF"
    assert written_off["written_off_reason"] == "Client became insolvent."
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 0


def test_peer_review_link_requires_both_endpoints_of_the_association(api):
    """PRD 2.10: "Foreign keys supplied inside a request body are resolved after
    the path and are checked in the order in which the endpoint declares its input
    fields, again returning the not-found code of the first unresolvable
    reference." PRD 3.6: "The review is created in `ASSIGNED` with
    `technical_score`, `collaboration_score`, `client_service_score`,
    `composite_score`, `comment` and `recusal_reason` all null, and returns 201
    Created."

    Design: Corner/endpoints/peer_review_link_requires_both_endpoints_of_the_association
    """
    cycle = create_cycle(api)
    subject = create_partner(api, full_name="Sue Bject")
    reviewer = create_partner(api, full_name="Rev Iewer", practice_group="TAX")
    assessment = create_assessment(api, cycle_id=cycle["id"], partner_id=subject["id"])

    # The assessment is declared first, so an unresolvable one wins.
    no_assessment = api.create_peer_review(
        create_peer_review_payload(UNKNOWN_UUID, reviewer["id"]), ADMIN
    )
    validate_error(no_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value, 404)

    no_reviewer = api.create_peer_review(
        create_peer_review_payload(assessment["id"], UNKNOWN_UUID), ADMIN
    )
    validate_error(no_reviewer, ApiErrorId.ERR_PARTNER_NOT_FOUND.value, 404)

    _nothing, empty_meta = validate_paginated(api.list_peer_reviews(ADMIN))
    assert empty_meta["total_count"] == 0

    review = validate_success(
        api.create_peer_review(
            create_peer_review_payload(assessment["id"], reviewer["id"]), ADMIN
        ),
        201,
    )
    assert review["state"] == "ASSIGNED"
    assert review["self_assessment_id"] == assessment["id"]
    assert review["reviewer_partner_id"] == reviewer["id"]
    assert review["technical_score"] is None
    assert review["collaboration_score"] is None
    assert review["client_service_score"] is None
    assert review["composite_score"] is None
    assert review["comment"] is None
    assert review["recusal_reason"] is None
    assert review["version"] == 1

    by_assessment, _assessment_meta = validate_paginated(
        api.list_peer_reviews(ADMIN, {"self_assessment_id": assessment["id"]})
    )
    by_reviewer, _reviewer_meta = validate_paginated(
        api.list_peer_reviews(ADMIN, {"reviewer_partner_id": reviewer["id"]})
    )
    assert [row["id"] for row in by_assessment] == [review["id"]]
    assert [row["id"] for row in by_reviewer] == [review["id"]]

    assert read_assessment(api, assessment["id"])["scored_review_count"] == 0
