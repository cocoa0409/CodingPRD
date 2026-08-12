"""Document validity windows, the resubmission cap and the capped photo retake cycle."""

from test_helpers import (
    ApiErrorId,
    add_photo,
    check_photo,
    list_applicant_documents,
    list_applicant_photos,
    new_applicant,
    new_catalog_item,
    new_document_requirement,
    new_order,
    read_applicant,
    read_document,
    read_order,
    resubmit_doc,
    retake_photo,
    review_doc,
    set_clock,
    submit_doc,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CASE_MANAGER, REVIEWER


# ==========================================================================
# The two validity windows anchor on different ends of the trip
# ==========================================================================
def _two_anchor_scenario():
    """One catalogue carrying both validity rules, and one traveller who has filed the
    same pair of document dates into both slots."""
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    new_document_requirement(
        catalog["id"],
        doc_type="PASSPORT_BOOK",
        is_required=True,
        validity_rule="VALID_BEYOND_RETURN_MONTHS",
        validity_param=6,
    )
    new_document_requirement(
        catalog["id"],
        doc_type="EMPLOYMENT_LETTER",
        is_required=True,
        validity_rule="EXPIRES_AFTER_ISSUE_DAYS",
        validity_param=300,
    )
    order = new_order(catalog["id"], travel_date="2026-07-01", return_date="2026-07-20")
    applicant = new_applicant(order["id"], full_name="Doc Anchor")
    passport = submit_doc(
        applicant["id"], doc_type="PASSPORT_BOOK", issue_date="2026-04-10", expiry_date="2026-12-31"
    )
    letter = submit_doc(
        applicant["id"],
        doc_type="EMPLOYMENT_LETTER",
        issue_date="2026-04-10",
        expiry_date="2026-12-31",
    )
    return order, applicant, passport, letter


def test_issue_anchored_document_accepts_the_dates_the_return_anchor_refuses(api):
    """PRD §3.7: "With `validity_rule` `EXPIRES_AFTER_ISSUE_DAYS` the slot is valid when
    its `issue_date` advanced by `validity_param` calendar days lands on or after the
    order's `travel_date`."
    PRD §3.7: "With `validity_rule` `VALID_BEYOND_RETURN_MONTHS` the slot is valid when its
    `expiry_date` is on or after the order's `return_date` advanced by `validity_param`
    calendar months, where advancing by months clamps to the last day of a shorter target
    month (a 31 January anchor advanced one month lands on 28 or 29 February)."
    PRD §3.7: "A slot that fails is refused with `ERR_DOCUMENT_VALIDITY_INSUFFICIENT` and
    stays in `RECEIVED`."

    Design: Difficulty/dual_variant_calc/document_validity_anchor_return_date_versus_travel_date
    """
    _order, _applicant, passport, letter = _two_anchor_scenario()

    # 2026-04-10 advanced by 300 days lands on 2027-02-04, comfortably on or
    # after the 2026-07-01 departure.
    accepted = validate_success(
        api.review_document(letter["id"], {"decision": "ACCEPT"}, REVIEWER)
    )
    assert accepted["review_status"] == "ACCEPTED"

    # 2026-07-20 advanced by 6 months lands on 2027-01-20, strictly after the
    # 2026-12-31 expiry.
    refused = api.review_document(passport["id"], {"decision": "ACCEPT"}, REVIEWER)
    validate_error(refused, ApiErrorId.ERR_DOCUMENT_VALIDITY_INSUFFICIENT.value)
    assert read_document(passport["id"])["review_status"] == "RECEIVED", (
        "a slot that fails the validity window stays in RECEIVED"
    )


def test_document_validity_failure_leaves_the_traveller_short_of_readiness(api):
    """PRD §3.4: "`accepted_doc_count` counts the traveller's document slots whose
    `doc_type` lies in the derived required set and whose `review_status` is `ACCEPTED`."
    PRD §3.4: "`required_doc_count` is the number of applying lines whose `is_required` is
    true."
    PRD §3.7: "The two windows anchor on different ends of the trip — one on the return,
    one on the departure — so the very same pair of document dates can pass one rule and
    fail the other."

    Design: Difficulty/dual_variant_calc/document_validity_anchor_return_date_versus_travel_date
    """
    _order, applicant, passport, letter = _two_anchor_scenario()

    validate_success(api.review_document(letter["id"], {"decision": "ACCEPT"}, REVIEWER))
    refused = api.review_document(passport["id"], {"decision": "ACCEPT"}, REVIEWER)
    validate_error(refused, ApiErrorId.ERR_DOCUMENT_VALIDITY_INSUFFICIENT.value)

    stored = read_applicant(applicant["id"])
    assert stored["accepted_doc_count"] == 1, (
        f"only the issue-anchored slot was accepted, got {stored['accepted_doc_count']}"
    )
    assert stored["required_doc_count"] == 2
    assert stored["readiness_status"] == "PENDING"


# ==========================================================================
# The capped photo retake cycle
# ==========================================================================
def _failing_photo_lineage():
    """Four chained photo submissions, each failing the head-height criterion."""
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Photo Loop")

    first = add_photo(applicant["id"], taken_on="2026-05-20", head_height_ratio=0.80)
    check_photo(first["id"])
    lineage = [first]
    for day in ("2026-05-21", "2026-05-22", "2026-05-23"):
        nxt = retake_photo(lineage[-1]["id"], taken_on=day, head_height_ratio=0.80)
        check_photo(nxt["id"])
        lineage.append(nxt)
    return applicant, lineage


def test_fourth_retake_of_a_photo_lineage_is_refused_at_the_cap(api):
    """PRD §3.7: "The source photo moves to `SUPERSEDED`, which is terminal, and a new
    photo is created in `PENDING` with `retake_count` one higher than the source's. A
    lineage supports at most **3** retakes; a fourth is `ERR_PHOTO_RETAKE_CAP_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/photo_capped_retake_cycle_on_photo_asset
    """
    applicant, lineage = _failing_photo_lineage()
    fourth = lineage[-1]

    resp = api.retake_photo(
        fourth["id"],
        {
            "taken_on": "2026-05-24",
            "head_height_ratio": 0.55,
            "background_code": "WHITE",
            "resolution_px": 800,
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_PHOTO_RETAKE_CAP_EXCEEDED.value)

    rows = list_applicant_photos(applicant["id"])
    assert len(rows) == 4, f"the refused retake creates no photo; expected 4 rows, got {len(rows)}"


def test_photo_retake_chain_supersedes_each_source_and_counts_up_to_the_cap(api):
    """PRD §3.7: "1. `HEAD_HEIGHT` fails unless `head_height_ratio` lies between **0.50**
    and **0.69** inclusive at both ends, compared to two decimal places."
    PRD §3.7: "A non-empty list moves the photo `PENDING → FAILED` and stores the list."
    PRD §2.9: "| 23 | `ERR_PHOTO_RETAKE_CAP_EXCEEDED` | 409 | On retake only,
    `retake_count` is below 3. |"

    Design: Difficulty/non_linear_state_machine/photo_capped_retake_cycle_on_photo_asset
    """
    applicant, lineage = _failing_photo_lineage()
    rows = {r["id"]: r for r in list_applicant_photos(applicant["id"])}

    first, fourth = lineage[0], lineage[-1]
    assert rows[first["id"]]["compliance_status"] == "SUPERSEDED", (
        "the source of a retake is superseded, which is terminal"
    )
    assert rows[first["id"]]["retake_count"] == 0, "the head of the lineage was never a retake"
    assert rows[fourth["id"]]["compliance_status"] == "FAILED"
    assert rows[fourth["id"]]["retake_count"] == 3, (
        f"three retakes have been consumed, got {rows[fourth['id']]['retake_count']}"
    )
    assert rows[fourth["id"]]["failure_reasons"] == ["HEAD_HEIGHT"], (
        "0.80 breaks only the head-height criterion"
    )


# ==========================================================================
# Compliance criteria, travel-date knock-on, resubmission cap, 404
# ==========================================================================
def test_photo_criteria_bounds_are_inclusive_and_failures_are_ordered(api):
    """PRD §3.7: "2. `BACKGROUND` fails when `background_code` is `COLORED`. `WHITE` and
    `OFF_WHITE` both pass."
    PRD §3.7: "3. `RESOLUTION` fails when `resolution_px` is strictly below **600**.
    Exactly 600 passes."
    PRD §3.7: "The list is built in that order — head height, then background, then
    resolution — and written verbatim to `failure_reasons`."

    Design: Corner/state_machines/corner_photo_passes_on_inclusive_head_height_bounds
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Photo Bounds")

    low = add_photo(
        applicant["id"], head_height_ratio=0.50, background_code="WHITE", resolution_px=600
    )
    high = add_photo(
        applicant["id"], head_height_ratio=0.69, background_code="OFF_WHITE", resolution_px=601
    )
    over = add_photo(
        applicant["id"], head_height_ratio=0.70, background_code="WHITE", resolution_px=800
    )
    multi = add_photo(
        applicant["id"], head_height_ratio=0.60, background_code="COLORED", resolution_px=599
    )

    low_checked = validate_success(api.run_compliance_check(low["id"], REVIEWER))
    high_checked = validate_success(api.run_compliance_check(high["id"], REVIEWER))
    over_checked = validate_success(api.run_compliance_check(over["id"], REVIEWER))
    multi_checked = validate_success(api.run_compliance_check(multi["id"], REVIEWER))

    assert low_checked["compliance_status"] == "PASSED", "0.50 is inclusive"
    assert high_checked["compliance_status"] == "PASSED", "0.69 is inclusive, and 600 px passes"
    assert over_checked["compliance_status"] == "FAILED"
    assert over_checked["failure_reasons"] == ["HEAD_HEIGHT"]
    assert multi_checked["compliance_status"] == "FAILED"
    assert multi_checked["failure_reasons"] == ["BACKGROUND", "RESOLUTION"], (
        "failures are listed head height, then background, then resolution"
    )


def test_travel_date_change_returns_an_accepted_document_to_received(api):
    """PRD §3.9: "Every document slot in `ACCEPTED` whose `validity_rule` is anything other
    than `NONE` falls back to `RECEIVED` and must be re-reviewed — with
    `resubmission_count` untouched, `issue_date` and `expiry_date` untouched, and
    `reviewed_by_user_id` and `rejection_reason` left as they stand."
    PRD §3.9: "The projection and feasibility verdict are re-run and any acknowledgment
    revoked."

    Design: Corner/state_machines/corner_travel_date_change_reverts_accepted_document_to_received
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    new_document_requirement(catalog["id"])
    order = new_order(catalog["id"], travel_date="2026-09-01", return_date="2026-09-20")
    applicant = new_applicant(order["id"], full_name="Date Shift")
    document = submit_doc(applicant["id"])
    review_doc(document["id"], "ACCEPT")
    assert read_applicant(applicant["id"])["accepted_doc_count"] == 1

    validate_success(
        api.change_travel_dates(
            order["id"], {"travel_date": "2026-10-01", "return_date": "2026-10-20"}, CASE_MANAGER
        )
    )

    stored_doc = read_document(document["id"])
    assert stored_doc["review_status"] == "RECEIVED"
    assert stored_doc["resubmission_count"] == 0, (
        "the fall-back path does not consume a resubmission"
    )
    stored_applicant = read_applicant(applicant["id"])
    assert stored_applicant["accepted_doc_count"] == 0
    assert stored_applicant["readiness_status"] == "PENDING"
    stored_order = read_order(order["id"])
    assert stored_order["travel_date"] == "2026-10-01"
    assert stored_order["feasibility_status"] != "UNKNOWN", (
        "the verdict is re-run on every travel-date change"
    )


def test_third_document_resubmission_is_refused_at_the_cap(api):
    """PRD §3.7: "That moves `REJECTED → RECEIVED`, overwrites both dates, clears
    `rejection_reason` to null and increments `resubmission_count`. A slot may be
    re-supplied at most **twice**; a third attempt is `ERR_RESUBMISSION_CAP_EXCEEDED`."

    Design: Corner/errors/corner_error_document_resubmission_cap_exceeded
    """
    set_clock()
    catalog = new_catalog_item(visa_type="TOURIST")
    new_document_requirement(catalog["id"])
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Resub Cap")
    document = submit_doc(applicant["id"])

    review_doc(document["id"], "REJECT", "blurred page")
    resubmit_doc(document["id"])
    review_doc(document["id"], "REJECT", "still blurred")
    resubmit_doc(document["id"])
    review_doc(document["id"], "REJECT", "wrong page")

    resp = api.resubmit_document(
        document["id"], {"issue_date": "2020-01-15", "expiry_date": "2030-01-15"}, CASE_MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_RESUBMISSION_CAP_EXCEEDED.value)

    stored = read_document(document["id"])
    assert stored["resubmission_count"] == 2
    assert stored["review_status"] == "REJECTED"
    assert read_order(order["id"])["custody_holder"] == "APPLICANT", (
        "the agency gate is inactive, so the cap rung is the one that fires"
    )


def test_unknown_document_id_is_the_generic_resource_not_found(api):
    """PRD §2.4: "Every other identifier — whether it appears later in the path or inside
    the request body as a foreign key — is resolved afterwards, also left to right, and a
    miss is `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/corner_error_resource_not_found_on_document_read
    """
    set_clock()
    resp = api.get_document("00000000-0000-4000-8000-0000000000aa", REVIEWER)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
