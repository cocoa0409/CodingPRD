"""Declared cross-cutting layers: version guards, paged filters and the sweep epoch."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
SECOND_TOUR_UTC = "2026-08-15T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
SECOND_EXECUTION_UTC = "2026-08-15T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


def test_all_three_version_guards_refuse_a_replayed_parent_version():
    """Each dependent create bumps its parent, and the replay is a 412 on all three.

    The PRD states: "Submitting a financing application (`POST
    /financing-applications`) requires `expected_agreement_version` to equal the target
    `PurchaseAgreement`'s current `version`. A mismatch is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Product semantics deliberately allow a
    newer application to supersede a prior one, so no state precondition blocks a
    second sequential submission; the stale-version guard is the only thing that stops
    a writer from superseding an approval it never saw. A successful submission itself
    increments the agreement's `version` by one."

    The PRD states: "Filing a prohibited-claim finding (`POST
    /prohibited-claim-findings`) requires `expected_presentation_version` to equal the
    target `SalesPresentation`'s current `version`. A mismatch is rejected with
    `ERR_STALE_PRESENTATION_VERSION` (HTTP 412). Multiple findings on one presentation
    are legitimate, so no state precondition blocks a second sequential append; the
    guard is what stops an officer from scoring a presentation whose `compliance_score`
    already moved beneath them. A successful append increments the presentation's
    `version` by one."

    The PRD states: "Assigning compliance retraining (`POST /retraining-assignments`)
    requires `expected_representative_version` to equal the target
    `SalesRepresentative`'s current `version`. A mismatch is rejected with
    `ERR_STALE_REPRESENTATIVE_VERSION` (HTTP 412). Assignments with distinct trigger
    reasons may coexist on one representative, so the reason-uniqueness rule does not
    block a second sequential create; the guard is what stops an officer from assigning
    against a representative whose strike count or status already changed. A successful
    create increments the representative's `version` by one."

    The PRD states: "The stale-version guards of §2.8 —
    `ERR_STALE_AGREEMENT_VERSION`, `ERR_STALE_PRESENTATION_VERSION` or
    `ERR_STALE_REPRESENTATIVE_VERSION` (412) — on exactly `POST
    /financing-applications`, `POST /prohibited-claim-findings` and `POST
    /retraining-assignments`."

    The PRD states: "Retraining reason uniqueness — `ERR_RETRAINING_ALREADY_ACTIVE`
    (409), on `POST /retraining-assignments`."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_stale_parent_versions
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_open_presentation(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
    )
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]
    fx.acknowledge_required_disclosures(presentation_id, rep_id)

    presentation_version = fx.read_presentation(presentation_id)["version"]
    fx.file_claim_finding(
        presentation_id,
        "MINOR",
        presentation_version,
        headers=OFFICER_BRAVO,
    )
    after_finding = fx.read_presentation(presentation_id)
    assert after_finding["version"] == presentation_version + 1
    assert after_finding["prohibited_claim_points"] == 5

    stale_finding = api.create_prohibited_claim_finding(
        fac.create_prohibited_claim_finding_payload(
            presentation_id,
            "MINOR",
            presentation_version,
            claim_code="UNLIMITED_AVAILABILITY",
        ),
        OFFICER_BRAVO,
    )
    validate_error(
        stale_finding, ApiErrorId.ERR_STALE_PRESENTATION_VERSION.value, 412
    )
    assert fx.read_presentation(presentation_id)["prohibited_claim_points"] == 5
    findings, findings_meta = validate_paginated(
        api.list_presentation_prohibited_claim_findings(presentation_id, OFFICER_ALPHA)
    )
    assert findings_meta["total_count"] == 1
    assert findings[0]["claim_code"] == "RENTAL_INCOME_PROMISE"

    fx.review_presentation(presentation_id, "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(presentation_id, rep_id)

    fx.pin_clock(EXECUTION_UTC)
    agreement = fx.execute_agreement(
        presentation_id,
        rep_id,
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at=POS_DELIVERED_AT,
    )
    agreement_version = fx.read_agreement(agreement["id"])["version"]
    application = fx.submit_financing(
        agreement["id"], rep_id, agreement_version, applicant_fico=760
    )
    assert fx.read_agreement(agreement["id"])["version"] == agreement_version + 1

    stale_application = api.create_financing_application(
        fac.create_financing_application_payload(
            agreement["id"], agreement_version, applicant_fico=700
        ),
        fx.make_sales_representative_headers(rep_id),
    )
    validate_error(
        stale_application, ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value, 412
    )
    assert fx.read_financing_application(application["id"])["status"] == "SUBMITTED"

    representative_version = fx.read_representative(rep_id)["version"]
    fx.assign_retraining(rep_id, representative_version, "DISCLOSURE_GAP")
    assert fx.read_representative(rep_id)["version"] == representative_version + 1

    stale_assignment = api.create_retraining_assignment(
        fac.create_retraining_assignment_payload(
            rep_id, representative_version, "DISCLOSURE_GAP"
        ),
        OFFICER_ALPHA,
    )
    validate_error(
        stale_assignment, ApiErrorId.ERR_STALE_REPRESENTATIVE_VERSION.value, 412
    )

    assignments, assignments_meta = validate_paginated(
        api.list_retraining_assignments(OFFICER_ALPHA, params={"rep_id": rep_id})
    )
    assert assignments_meta["total_count"] == 1
    assert assignments[0]["trigger_reason"] == "DISCLOSURE_GAP"


def test_paging_walks_a_filtered_roster_rather_than_the_whole_table():
    """Three Orlando rows page two-then-one while the Las Vegas row stays out of scope.

    The PRD states: "`limit` caps the number of records returned; it defaults to 10,
    its minimum accepted value is 1 and its maximum accepted value is 100."

    The PRD states: "`offset` skips a number of leading records and defaults to 0; its
    minimum accepted value is 0."

    The PRD states: "A `limit` outside the range of 1 to 100, or a negative `offset`,
    is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    The PRD states: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object, where `total_count` counts every record matching
    the supplied filters before pagination is applied and `has_more` is true exactly
    when records matching the filters remain beyond the current page."

    The PRD states: "Representatives can be listed with optional `gallery_id` and
    `status` filters alongside `limit` and `offset`."

    The PRD states: "Unless a specific endpoint says otherwise, every list is sorted
    by `created_at` in ascending order."

    Design: Corner/cross_cutting_complexity_layers/representative_list_pagination_interacts_with_filters
    """
    fx.pin_clock(CLOCK_START)
    orlando = fx.create_gallery()
    las_vegas = fx.create_gallery(name="Las Vegas Sales Gallery", site_code="LVSGAL")
    orlando_roster = fx.create_representatives(orlando["id"], 3)
    las_vegas_rep = fx.create_representative(
        las_vegas["id"],
        full_name="Ana Solis",
        license_number="NV-SL-810080",
        rotation_position=1,
    )

    first_page, first_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY, params={"gallery_id": orlando["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert [row["id"] for row in first_page] == [
        orlando_roster[0]["id"],
        orlando_roster[1]["id"],
    ]

    last_page, last_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY, params={"gallery_id": orlando["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(last_page) == 1
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False
    assert last_page[0]["id"] == orlando_roster[2]["id"]

    other_gallery, other_meta = validate_paginated(
        api.list_sales_representatives(GALLERY, params={"gallery_id": las_vegas["id"]})
    )
    assert other_meta["total_count"] == 1
    assert other_meta["limit"] == 10
    assert other_meta["offset"] == 0
    assert other_gallery[0]["id"] == las_vegas_rep["id"]

    suspended, suspended_meta = validate_paginated(
        api.list_sales_representatives(
            GALLERY, params={"gallery_id": orlando["id"], "status": "SUSPENDED"}
        )
    )
    assert suspended == []
    assert suspended_meta["total_count"] == 0
    assert suspended_meta["has_more"] is False

    validate_error(
        api.list_sales_representatives(GALLERY, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )


def test_the_sweep_expires_only_what_the_clock_has_strictly_passed():
    """Nevada expires first, the replay finds nothing, and Florida waits for the 26th.

    The PRD states: "A `PlatformAdmin` advances it, and every agreement whose
    `rescission_status` is `OPEN` and whose `rescission_deadline_utc` lies strictly
    behind the logical clock moves `OPEN → EXPIRED`."

    The PRD states: "Agreements are processed in `executed_at` ascending order with
    `created_at` ascending as the tie-break, `fulfillment_status` is never touched by
    the sweep, and the response reports `swept_count`, the list of
    `expired_agreement_ids`, and the `clock_now` the sweep ran at."

    The PRD states: "An agreement exactly at its deadline instant is not swept, because
    the comparison is strict."

    Design: Corner/cross_cutting_complexity_layers/rescission_sweep_is_ordered_idempotent_and_scope_limited
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    first_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )
    second_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=SECOND_TOUR_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    fx.check_in(first_booking["id"], issue_incentive_gift=False)
    first_presentation = fx.open_presentation(first_booking["id"], representative["id"])
    fx.acknowledge_required_disclosures(first_presentation["id"], representative["id"])
    fx.review_presentation(first_presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(first_presentation["id"], representative["id"])

    fx.pin_clock(EXECUTION_UTC)
    nevada = fx.execute_agreement(
        first_presentation["id"],
        representative["id"],
        state_code="NV",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at=POS_DELIVERED_AT,
    )
    assert_instant_equals(
        nevada["rescission_deadline_utc"],
        "2026-08-19T23:59:59.999Z",
        "rescission_deadline_utc",
    )

    fx.pin_clock(SECOND_TOUR_UTC)
    fx.check_in(second_booking["id"], issue_incentive_gift=False)
    second_presentation = fx.open_presentation(
        second_booking["id"], representative["id"], recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(second_presentation["id"], representative["id"])
    fx.review_presentation(second_presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(second_presentation["id"], representative["id"])

    fx.pin_clock(SECOND_EXECUTION_UTC)
    florida = fx.execute_agreement(
        second_presentation["id"],
        representative["id"],
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at="2026-08-11T10:00:00Z",
    )
    assert_instant_equals(
        florida["rescission_deadline_utc"],
        "2026-08-25T23:59:59.999Z",
        "rescission_deadline_utc",
    )

    fx.pin_clock("2026-08-20T00:00:00Z")
    first_sweep = validate_success(api.run_rescission_sweep(PLATFORM))
    assert first_sweep["swept_count"] == 1
    assert first_sweep["expired_agreement_ids"] == [nevada["id"]]
    assert_instant_equals(
        first_sweep["clock_now"], "2026-08-20T00:00:00Z", "clock_now"
    )

    replay = validate_success(api.run_rescission_sweep(PLATFORM))
    assert replay["swept_count"] == 0
    assert replay["expired_agreement_ids"] == []

    fx.pin_clock("2026-08-25T00:00:00Z")
    at_the_deadline = validate_success(api.run_rescission_sweep(PLATFORM))
    assert at_the_deadline["swept_count"] == 0
    assert at_the_deadline["expired_agreement_ids"] == []

    fx.pin_clock("2026-08-26T00:00:00Z")
    final_sweep = validate_success(api.run_rescission_sweep(PLATFORM))
    assert final_sweep["swept_count"] == 1
    assert final_sweep["expired_agreement_ids"] == [florida["id"]]

    for agreement_id in (nevada["id"], florida["id"]):
        stored = fx.read_agreement(agreement_id)
        assert stored["rescission_status"] == "EXPIRED"
        assert stored["fulfillment_status"] == "AWAITING_FUNDING"
        assert stored["funded_at"] is None
