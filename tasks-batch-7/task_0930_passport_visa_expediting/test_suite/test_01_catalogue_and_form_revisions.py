"""Product catalogue paperwork, government form revisions and the staleness cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_agency_form,
    assert_prepared_form,
    list_prepared_forms,
    new_active_form,
    new_agency_form,
    new_applicant,
    new_catalog_item,
    new_document_requirement,
    new_leg,
    new_order,
    read_applicant,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import build_scenario, applicant_version, add_photo, check_photo
from test_helpers.api_client import api_client
from test_helpers.fixtures import ADMIN, CASE_MANAGER


# ==========================================================================
# Catalogue paperwork
# ==========================================================================
def test_document_requirement_validity_param_defaults_per_rule(api):
    """PRD §3.1: "Omitting `validity_param` is normal and the stored default depends on
    the rule: a `VALID_BEYOND_RETURN_MONTHS` line stores **6 months**, and an
    `EXPIRES_AFTER_ISSUE_DAYS` line stores **90 days**."

    Design: Corner/entities/corner_document_requirement_validity_param_default_applied
    """
    set_clock()
    catalog = new_catalog_item()

    validate_success(
        api.create_document_requirement(
            catalog["id"],
            {
                "doc_type": "PASSPORT_BOOK",
                "is_required": True,
                "validity_rule": "VALID_BEYOND_RETURN_MONTHS",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_document_requirement(
            catalog["id"],
            {
                "doc_type": "BANK_STATEMENT",
                "is_required": False,
                "validity_rule": "EXPIRES_AFTER_ISSUE_DAYS",
            },
            ADMIN,
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(api.list_document_requirements(catalog["id"], ADMIN))
    assert meta["total_count"] == 2, f"expected 2 requirement lines, got {meta['total_count']}"
    stored = {row["doc_type"]: row for row in rows}

    assert stored["PASSPORT_BOOK"]["validity_param"] == 6, (
        "a VALID_BEYOND_RETURN_MONTHS line with no validity_param stores 6 months, "
        f"got {stored['PASSPORT_BOOK']['validity_param']}"
    )
    assert stored["BANK_STATEMENT"]["validity_param"] == 90, (
        "an EXPIRES_AFTER_ISSUE_DAYS line with no validity_param stores 90 days, "
        f"got {stored['BANK_STATEMENT']['validity_param']}"
    )


def test_traveler_may_not_publish_a_form_revision(api):
    """PRD §3.2: "Publishing is the single most disruptive operation in the system, and it
    is a `PlatformAdmin` capability."
    PRD §2.1: "Once authenticated, a role that does not appear in the called endpoint's
    authorized-role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_traveler_cannot_publish_agency_form_unauthorized
    """
    set_clock()
    form = new_agency_form()

    resp = api.publish_agency_form(form["id"], TEST_USERS["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    stored = validate_success(api.get_agency_form(form["id"], ADMIN))
    assert_agency_form(stored)
    assert stored["status"] == "DRAFT", "a refused publish leaves the revision in DRAFT"
    assert stored["published_at"] is None, "published_at stays null on a refused publish"


# ==========================================================================
# Preparing a form depends on the referenced revision's publication state
# ==========================================================================
def test_prepare_form_against_a_draft_revision_is_refused(api):
    """PRD §3.7: "The named revision must currently hold `status` `ACTIVE` **and** its
    `form_code` must equal the `form_code` on the order's catalog item; otherwise the
    request is `ERR_FORM_REVISION_STALE`."
    PRD §3.1: "A newly registered revision has `status` `DRAFT` and a null `published_at`."

    Design: Difficulty/cross_entity_state_dependency/prepared_form_creation_depends_on_agency_form_publication_state
    """
    set_clock()
    form = new_agency_form()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Form Dep")

    resp = api.create_prepared_form(
        applicant["id"],
        {
            "agency_form_id": form["id"],
            "filled_field_count": 12,
            "expected_applicant_version": applicant["version"],
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FORM_REVISION_STALE.value)

    rows, meta = validate_paginated(api.list_applicant_prepared_forms(applicant["id"], CASE_MANAGER))
    assert meta["total_count"] == 0, "a refused preparation writes no PreparedForm row"
    assert rows == []


def test_prepare_form_succeeds_the_moment_the_same_revision_is_published(api):
    """PRD §2.9: "| 24 | `ERR_FORM_REVISION_STALE` | 409 | On preparing a form only, the
    named `AgencyForm` has `status` `ACTIVE` and its `form_code` equals the order's catalog
    item's `form_code`. |"
    PRD §3.7: "The new preparation is created in `prep_status` `PREPARED`, copying
    `form_code` and `revision_used` from the referenced revision."

    Design: Difficulty/cross_entity_state_dependency/prepared_form_creation_depends_on_agency_form_publication_state
    """
    set_clock()
    form = new_agency_form()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Form Dep")
    observed_version = applicant["version"]

    refused = api.create_prepared_form(
        applicant["id"],
        {
            "agency_form_id": form["id"],
            "filled_field_count": 12,
            "expected_applicant_version": observed_version,
        },
        CASE_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_FORM_REVISION_STALE.value)

    validate_success(api.publish_agency_form(form["id"], ADMIN))

    # Nothing about the applicant changed between the two attempts, so the
    # version the client observed is still current.
    accepted = validate_success(
        api.create_prepared_form(
            applicant["id"],
            {
                "agency_form_id": form["id"],
                "filled_field_count": 12,
                "expected_applicant_version": observed_version,
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    assert_prepared_form(accepted)
    assert accepted["prep_status"] == "PREPARED"
    assert accepted["revision_used"] == 1, "revision_used is copied from the referenced revision"
    assert accepted["form_code"] == "DS-160", "form_code is copied from the referenced revision"
    assert read_applicant(applicant["id"])["readiness_status"] == "PENDING", (
        "a preparation alone does not complete a traveller"
    )


def test_prepared_form_create_rejects_a_stale_applicant_version(api):
    """PRD §2.8: "`POST /expediting/applicants/{id}/prepared-forms` requires
    `expected_applicant_version`, carrying the client's last observed `version` of the
    target `Applicant`."
    PRD §2.8: "If the applicant's `version` has advanced since the client last read it,
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_applicant_version_rejects_prepared_form
    """
    set_clock()
    form = new_active_form()
    catalog = new_catalog_item(visa_type="PASSPORT_RENEWAL")
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Occ One")
    observed_version = applicant_version(applicant["id"])

    first = validate_success(
        api.create_prepared_form(
            applicant["id"],
            {
                "agency_form_id": form["id"],
                "filled_field_count": 12,
                "expected_applicant_version": observed_version,
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )

    resp = api.create_prepared_form(
        applicant["id"],
        {
            "agency_form_id": form["id"],
            "filled_field_count": 12,
            "expected_applicant_version": observed_version,
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    stored_first = validate_success(api.get_agency_form(form["id"], ADMIN))
    assert stored_first["status"] == "ACTIVE"
    rows = list_prepared_forms(applicant["id"])
    assert len(rows) == 1, f"the refused create writes no row; expected 1, got {len(rows)}"
    assert rows[0]["id"] == first["id"]
    assert rows[0]["prep_status"] == "PREPARED", "the surviving preparation is untouched"


def test_second_preparation_supersedes_the_prior_one_to_void(api):
    """PRD §3.7: "Creating it is a supersede: any prior preparation of the same traveller
    carrying the same `form_code` moves to `VOID`, whether it stood in `PREPARED` or in
    `STALE`, and `VOID` is terminal."
    PRD §3.7: "A traveller moves `PENDING → COMPLETE` exactly when **all four** of the
    following hold: every one of their document slots whose `is_required` is true has
    `review_status` `ACCEPTED`; exactly one of their photos has `compliance_status`
    `PASSED`; exactly one of their preparations has `prep_status` `PREPARED` or `SIGNED`
    **and** a `revision_used` equal to the `revision` of the currently `ACTIVE` form
    carrying the product's `form_code`; and, when the order's catalog item has
    `requires_appointment` true, one of their appointments has `booking_status` `ATTENDED`."

    Design: Corner/cross_cutting_complexity_layers/corner_prepared_form_create_supersedes_prior_to_void
    """
    set_clock()
    form = new_active_form()
    catalog = new_catalog_item(visa_type="PASSPORT_RENEWAL")
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Void Chain")
    photo = add_photo(applicant["id"])
    check_photo(photo["id"])

    first = validate_success(
        api.create_prepared_form(
            applicant["id"],
            {
                "agency_form_id": form["id"],
                "filled_field_count": 12,
                "expected_applicant_version": applicant_version(applicant["id"]),
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_prepared_form(
            applicant["id"],
            {
                "agency_form_id": form["id"],
                "filled_field_count": 14,
                "expected_applicant_version": applicant_version(applicant["id"]),
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )

    rows = {r["id"]: r for r in list_prepared_forms(applicant["id"])}
    assert len(rows) == 2, f"both preparations remain readable, got {len(rows)}"
    assert rows[first["id"]]["prep_status"] == "VOID", "the prior preparation is superseded to VOID"
    assert rows[second["id"]]["prep_status"] == "PREPARED"
    assert second["filled_field_count"] == 14
    assert read_applicant(applicant["id"])["readiness_status"] == "COMPLETE", (
        "the surviving PREPARED form plus a PASSED photo completes the traveller"
    )


# ==========================================================================
# Publishing a revision and the five-hop staleness cascade
# ==========================================================================
def _scenario_ready_with_a_second_undispatched_hop():
    """Order at READY_FOR_SUBMISSION on DS-160 revision 1, plus a DRAFT revision 2
    and an undispatched SERVICE -> AGENCY hop."""
    scenario = build_scenario(
        "ready",
        require_passport_doc=True,
        visa_type="TOURIST",
    )
    scenario["form_v2"] = new_agency_form(revision=2, required_field_count=14)
    scenario["leg2"] = new_leg(
        scenario["order_id"],
        leg_index=2,
        from_holder="SERVICE",
        to_holder="AGENCY",
        scheduled_date="2026-06-02",
    )
    return scenario


def test_publishing_a_revision_supersedes_the_prior_one_and_stales_its_preparations(api):
    """PRD §3.2: "**Hop 1.** The revision of the same `form_code` that currently holds
    `status` `ACTIVE` — if there is one — moves `ACTIVE → SUPERSEDED`."
    PRD §3.2: "**Hop 2.** Because that revision is now `SUPERSEDED`, every preparation
    whose `agency_form_id` points at that exact revision and whose `prep_status` is
    `PREPARED` or `SIGNED` moves to `STALE`."
    PRD §3.2: "**Hop 3.** Because those preparations are `STALE`, every traveller who owns
    one and whose `readiness_status` is `COMPLETE` regresses `COMPLETE → PENDING`."

    Design: Difficulty/transitive_cascade/agency_form_revision_regresses_five_entity_hops
    """
    scenario = _scenario_ready_with_a_second_undispatched_hop()
    applicant_id = scenario["applicant_ids"][0]
    prepared_form_id = scenario["prepared_forms"][applicant_id]["id"]

    assert read_applicant(applicant_id)["readiness_status"] == "COMPLETE"

    published = validate_success(api.publish_agency_form(scenario["form_v2"]["id"], ADMIN))
    assert published["status"] == "ACTIVE", "the published revision moves DRAFT -> ACTIVE"
    assert published["published_at"] is not None, "published_at is stamped on publication"

    revision_one = validate_success(api.get_agency_form(scenario["form"]["id"], ADMIN))
    assert revision_one["status"] == "SUPERSEDED", "hop 1 supersedes the prior ACTIVE revision"

    prepared_rows = {r["id"]: r for r in list_prepared_forms(applicant_id)}
    assert prepared_rows[prepared_form_id]["prep_status"] == "STALE", (
        "hop 2 drives the preparation filled against revision 1 to STALE"
    )
    assert prepared_rows[prepared_form_id]["revision_used"] == 1, (
        "revision_used is never rewritten by the staleness hop"
    )
    assert read_applicant(applicant_id)["readiness_status"] == "PENDING", (
        "hop 3 regresses the traveller who owns the stale preparation"
    )


def test_publishing_a_revision_regresses_the_order_and_cancels_its_created_hops(api):
    """PRD §3.2: "**Hop 4.** Because those travellers regressed, every order that carries
    one of them and sits in `workflow_status` `READY_FOR_SUBMISSION` regresses
    `READY_FOR_SUBMISSION → INTAKE`, and its `feasibility_status` is reset to `UNKNOWN`."
    PRD §3.2: "Critically, `furthest_stage_reached` is a high-water mark and is **never
    lowered**: an order that had reached `READY_FOR_SUBMISSION` keeps that value in
    `furthest_stage_reached` even as `workflow_status` falls back to `INTAKE`, and the
    refund schedule keyed to it therefore does not improve."
    PRD §3.2: "**Hop 5.** Because those orders regressed, every courier leg belonging to
    them whose `leg_status` is `CREATED` moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/agency_form_revision_regresses_five_entity_hops
    """
    scenario = _scenario_ready_with_a_second_undispatched_hop()
    order_id = scenario["order_id"]
    leg1_id = scenario["legs"][0]["id"]
    leg2_id = scenario["leg2"]["id"]

    before = read_order(order_id)
    assert before["workflow_status"] == "READY_FOR_SUBMISSION"

    validate_success(api.publish_agency_form(scenario["form_v2"]["id"], ADMIN))

    after = read_order(order_id)
    assert after["workflow_status"] == "INTAKE", "hop 4 regresses the order to INTAKE"
    assert after["furthest_stage_reached"] == "READY_FOR_SUBMISSION", (
        "furthest_stage_reached is a high-water mark and is never lowered"
    )
    assert after["feasibility_status"] == "UNKNOWN", (
        "hop 4 resets feasibility_status to UNKNOWN"
    )
    assert after["custody_holder"] == "SERVICE", (
        "the paperwork cascade does not move the passport"
    )

    legs = {leg["id"]: leg for leg in validate_paginated(
        api.list_courier_legs(order_id, TEST_USERS["courier_ops_headers"])
    )[0]}
    assert legs[leg2_id]["leg_status"] == "CANCELLED", "hop 5 cancels the CREATED hop"
    assert legs[leg1_id]["leg_status"] == "DELIVERED", (
        "a hop already delivered is not recalled by a paperwork change"
    )
