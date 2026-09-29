"""Lifecycle behaviour: initial states, declared transitions, guards and terminals."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    DEFAULT_CLOCK,
    DEFAULT_CLOCK_MS,
    DIRECTOR_A,
    OFFICER_A,
    OFFICER_B,
    PRESERV_A,
    assert_common_fields,
    assert_fields,
    assert_nulls,
    factories as f,
    failed,
    fixtures as fx,
    make_requester_headers,
    ok,
)
from test_helpers.api_errors import (
    ERR_ACCESSION_STATE_INVALID,
    ERR_APPRAISAL_STATE_INVALID,
    ERR_HOLD_STATE_INVALID,
    ERR_ITEM_CONDITION_UNSUITABLE,
    ERR_PLAN_STATE_INVALID,
    ERR_REQUEST_STATE_INVALID,
    ERR_REQUESTER_STATE_INVALID,
    ERR_SERIES_DISPOSITION_SUSPENDED,
)


def test_a_new_accession_starts_in_received_with_both_counters_at_zero(client):
    """PRD §3.4: "The new accession enters `status` `RECEIVED` with `provenance_documented`
    false, `processed_unit_count` 0, `deaccessioned_unit_count` 0, and
    `provenance_statement`, `transfer_instrument_reference` and `rejection_reason` all null."
    PRD §3.4: "The accession lifecycle runs `RECEIVED`, `PROVENANCE_VERIFIED`, and the two
    terminal states `PROCESSED` and `REJECTED`."

    Design: Corner/state_machines/accession_starts_in_received_status_on_create
    """
    series = fx.make_series(
        client,
        title="General Files",
        business_unit="Administration",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=30,
        earliest_record_year=1975,
        latest_record_year=2001,
        schedule_overrides={"code": "GEN-05", "retention_years": 5,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 84.00},
    )

    accession = fx.make_accession(
        client,
        series["id"],
        donor_name="Administration Office",
        transfer_instrument="INTERNAL_TRANSFER",
        declared_unit_count=4,
    )

    assert_fields(
        accession,
        status="RECEIVED",
        provenance_documented=False,
        processed_unit_count=0,
        deaccessioned_unit_count=0,
    )
    assert_common_fields(accession, expected_version=1)


def test_verify_provenance_advances_the_accession_and_stores_both_strings(client):
    """PRD §3.4: "Provenance verification is the archivist's act of writing down where the
    material came from, and it advances the accession `RECEIVED → PROVENANCE_VERIFIED`."
    PRD §3.4: "The archivist supplies `provenance_statement`, the custodial-history
    narrative, and `transfer_instrument_reference`, the signed-instrument reference; both are
    stored on the accession and `provenance_documented` is set true."
    PRD §2.4: "All resources except one also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is
    created and increments by exactly 1 on every mutation of that row — including mutations
    the server performs on its own initiative as part of a cascade, and including mutations
    that only touch derived counters."

    Design: Corner/state_machines/accession_verify_provenance_moves_received_to_provenance_verified
    """
    holding = fx.make_holding(
        client,
        item_specs=[],
        declared_unit_count=2,
        stage="RECEIVED",
        schedule_overrides={"code": "GEN-06", "retention_years": 6,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 81.00},
        series_overrides={"title": "Facilities Records", "business_unit": "Facilities",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 16,
                          "earliest_record_year": 1968,
                          "latest_record_year": 2003},
        accession_overrides={"donor_name": "Facilities Office",
                             "transfer_instrument": "INTERNAL_TRANSFER"},
    )

    statement = "Chain of custody confirmed against the 1998 facilities inventory."
    verified = ok(client.verify_accession_provenance(
        holding.accession_id,
        f.verify_provenance_payload(
            provenance_statement=statement,
            transfer_instrument_reference="IT-2026-052",
        ),
        ARCHIVIST_A,
    ))

    assert_fields(
        verified,
        status="PROVENANCE_VERIFIED",
        provenance_documented=True,
        provenance_statement=statement,
        transfer_instrument_reference="IT-2026-052",
        version=2,
    )


def test_publication_stamps_the_clock_and_recounts_the_described_items(client):
    """PRD §3.5: "Publication belongs to the `ArchivesDirector` and is declared only from
    `UNDER_REVIEW`."
    PRD §3.5: "Publication stamps `published_at` from the logical clock — on every
    publication, so a republished aid carries the most recent instant — and recomputes
    `described_item_count`."
    PRD §3.5: "`described_item_count` is the number of items under the aid's accession whose
    status is anything other than `REJECTED_ITEM`."
    PRD §3.5: "`stale_item_count` is the number of items under that same accession whose
    status is `PENDING_DISPOSITION` or `DEACCESSIONED`."

    Design: Corner/state_machines/finding_aid_publish_moves_under_review_to_published_and_stamps_published_at
    """
    fx.set_clock(client, DEFAULT_CLOCK)
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "item_label": "AR-1930-2000",
                     "sensitivity_level": "PUBLIC"}],
        schedule_overrides={"code": "GEN-07", "retention_years": 7,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 79.00},
        series_overrides={"title": "Annual Reports",
                          "business_unit": "Investor Relations",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 8,
                          "earliest_record_year": 1930,
                          "latest_record_year": 2000},
    )
    aid = fx.reviewed_finding_aid(
        client,
        holding.accession_id,
        title="Guide to the Annual Reports",
        arrangement_level="COLLECTION",
        version_label="v1",
    )

    published = ok(client.publish_finding_aid(aid["id"], DIRECTOR_A))

    assert_fields(
        published,
        status="PUBLISHED",
        published_at=DEFAULT_CLOCK_MS,
        described_item_count=1,
        stale_item_count=0,
        revision_cycle_count=0,
    )


def test_signing_again_from_restricted_returns_consent_to_signed(client):
    """PRD §3.8: "Signing again from `RESTRICTED` moves it back to `SIGNED`, so `SIGNED` and
    `RESTRICTED` form a cycle the narrator's wishes may traverse repeatedly; note that
    `consent_signed_at` records when consent *first* became signed."
    PRD §3.8: "Withdrawing is declared from `SIGNED` and equally from `RESTRICTED`; either
    path moves consent to `WITHDRAWN`, increments `withdrawal_count` by 1, and forces
    `release_state` to `WITHHELD` irrespective of how far transcription has progressed."
    PRD §3.8: "Every consent action recomputes `release_state` and leaves
    `transcription_status` completely untouched."
    PRD §3.8: "When consent is `SIGNED`, the release state is `PUBLIC` if transcription has
    reached `APPROVED` **and** either there is no embargo or the logical clock stands at or
    after `embargo_until`; failing that, it is `RESEARCH_ROOM_ONLY` if transcription has
    reached `REVIEWED` or `APPROVED`; and `WITHHELD` in every remaining case."

    Design: Corner/state_machines/oral_history_consent_returns_from_restricted_to_signed_on_second_sign
    """
    holding = fx.make_holding(
        client,
        item_specs=[],
        declared_unit_count=1,
        stage="RECEIVED",
        schedule_overrides={"code": "OHP-12", "retention_years": 12,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 74.00},
        series_overrides={"title": "Oral History Program",
                          "business_unit": "Heritage Office",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 3,
                          "earliest_record_year": 1995,
                          "latest_record_year": 2020},
        accession_overrides={"donor_name": "Retiree Association",
                             "transfer_instrument": "DEED_OF_GIFT"},
    )
    interview = fx.interview_at(
        client,
        holding.accession_id,
        consent_actions=["SIGN", "RESTRICT"],
        narrator_name="H. Vogel",
        interview_date="2026-07-15T14:00:00Z",
    )
    assert interview["consent_status"] == "RESTRICTED"

    signed = ok(client.interview_consent(
        interview["id"], f.consent_payload("SIGN"), ARCHIVIST_A))

    assert_fields(
        signed,
        consent_status="SIGNED",
        withdrawal_count=0,
        transcription_status="NOT_STARTED",
        release_state="WITHHELD",
    )


def test_submitting_an_aid_over_an_unprocessed_accession_is_a_parent_state_error(client):
    """PRD §3.5: "From `DRAFT` the aid advances to `UNDER_REVIEW`, and this path additionally
    requires the parent accession to be in `PROCESSED` status — a submission over an
    unprocessed accession is refused with `ERR_ACCESSION_STATE_INVALID`."
    PRD §3.5: "The aid is created in `status` `DRAFT` with `described_item_count` and
    `stale_item_count` both 0, `revision_cycle_count` 0 and `published_at` null."

    Design: Corner/state_machines/finding_aid_submit_review_before_accession_processed_returns_accession_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[],
        declared_unit_count=3,
        stage="PROVENANCE_VERIFIED",
        schedule_overrides={"code": "GEN-08", "retention_years": 8,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 77.00},
        series_overrides={"title": "Sales Ledgers", "business_unit": "Finance",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 33,
                          "earliest_record_year": 1958,
                          "latest_record_year": 1997},
    )
    aid = fx.make_finding_aid(
        client,
        holding.accession_id,
        title="Guide to the Sales Ledgers",
        arrangement_level="SERIES",
        version_label="v1",
    )

    failed(
        client.submit_finding_aid_review(aid["id"], ARCHIVIST_A),
        ERR_ACCESSION_STATE_INVALID,
        409,
    )

    reloaded = fx.read_finding_aid(client, aid["id"])
    assert_fields(reloaded, status="DRAFT", described_item_count=0)
    assert fx.read_accession(client, holding.accession_id)["status"] == "PROVENANCE_VERIFIED"


def test_confirming_a_loan_over_poor_material_is_refused_and_moves_no_units(client):
    """PRD §3.8: "It requires the item to be in `ACCESSIONED` status, the item's
    `condition_grade` to be `GOOD` or `FAIR` — `POOR` and `UNSTABLE` material may not go on
    display, and the attempt is refused with `ERR_ITEM_CONDITION_UNSUITABLE` — and the item's
    `units_on_shelf` to be at least the loan's `units`, refusing otherwise with
    `ERR_INSUFFICIENT_SHELF_UNITS`."
    PRD §3.8: "No units move at confirmation."
    PRD §3.8: "The loan is created in `status` `REQUESTED` with `returned_condition_grade`,
    `checked_out_at` and `returned_at` null, and its `recovery_until` derived as `window_end`
    plus a 45-day light-recovery buffer — the effective end of this loan's occupation of the
    item, during which the material rests out of the light."

    Design: Corner/state_machines/exhibit_loan_confirm_on_poor_condition_item_returns_condition_unsuitable
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 4, "condition_grade": "POOR",
                     "original_format": "PHOTO", "sensitivity_level": "PUBLIC",
                     "item_label": "PROTO-1949"}],
        schedule_overrides={"code": "GEN-09", "retention_years": 9,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 73.00},
        series_overrides={"title": "Product Prototypes", "business_unit": "Design",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1940,
                          "latest_record_year": 1985},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        units=2,
        exhibit_name="Design Retrospective",
    )

    failed(
        client.confirm_exhibit_loan(loan["id"], PRESERV_A),
        ERR_ITEM_CONDITION_UNSUITABLE,
        422,
    )

    assert fx.read_loan(client, loan["id"])["status"] == "REQUESTED"
    item = fx.read_item(client, holding.item_id)
    assert_fields(item, status="ACCESSIONED", units_on_shelf=4, units_on_loan=0)


def test_legal_clearance_is_refused_while_the_item_s_series_carries_an_active_hold(client):
    """PRD §3.9: "Both paths require the item's governing series to have `legal_hold_active`
    false and to be in neither `SUSPENDED` disposition state, refusing otherwise with
    `ERR_SERIES_DISPOSITION_SUSPENDED`, nor `PERMANENT`, refusing otherwise with
    `ERR_SERIES_PERMANENT`."
    PRD §3.9: "The proposal is created in `status` `SUBMITTED` with `legal_cleared_by`,
    `heritage_cleared_by`, `approved_by`, `clearance_note` and `transfer_reference` all null,
    and `stale_finding_aid_count` and `revalidated_request_count` both 0."
    PRD §3.3: "Hop one suspends the series."
    PRD §3.3: "Whichever of `ACTIVE`, `ELIGIBLE_FOR_DISPOSITION` or `PERMANENT` the series
    currently occupies is copied verbatim into `pre_hold_disposition_state`, the series moves
    to `SUSPENDED`, `legal_hold_active` is set true, and the series' `version` increments with
    `updated_at` refreshed."

    Design: Corner/state_machines/deaccession_legal_clearance_while_series_hold_active_returns_series_disposition_suspended
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "sensitivity_level": "CONFIDENTIAL",
                     "item_label": "CONTRACTS-1990-2012"}],
        schedule_overrides={"code": "GEN-11", "retention_years": 11,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 86.00},
        series_overrides={"title": "Vendor Contracts", "business_unit": "Procurement",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 44,
                          "earliest_record_year": 1990,
                          "latest_record_year": 2012},
    )
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        units=3,
        rationale="Duplicate of the vendor master file.",
    )
    fx.active_hold(
        client, holding.series_id, matter_number="MAT-7712",
        effective_from="2026-08-01T00:00:00Z",
    )

    failed(
        client.legal_clearance(
            proposal["id"],
            COUNSEL_A,
            f.clearance_payload("Attempted clearance during litigation hold."),
        ),
        ERR_SERIES_DISPOSITION_SUSPENDED,
        409,
    )

    reloaded = fx.read_proposal(client, proposal["id"])
    assert reloaded["status"] == "SUBMITTED"
    assert_nulls(reloaded, "legal_cleared_by")
    series = fx.read_series(client, holding.series_id)
    assert_fields(series, disposition_state="SUSPENDED", legal_hold_active=True)


def test_releasing_the_hold_restores_the_series_and_unblocks_its_request(client):
    """PRD §3.3: "Release is the mirror image, declared only from `ACTIVE`."
    PRD §3.3: "Counsel supplies `release_note`, which is stored, and `released_at` is stamped
    from the logical clock."
    PRD §3.3: "Provided no other hold on the series remains `ACTIVE` after this release, the
    series restores `disposition_state` from `pre_hold_disposition_state` verbatim — a series
    that was `ACTIVE` before the hold returns to `ACTIVE`, one that was
    `ELIGIBLE_FOR_DISPOSITION` returns to `ELIGIBLE_FOR_DISPOSITION`, and one that was
    `PERMANENT` returns to `PERMANENT` — then `pre_hold_disposition_state` is set back to null
    and `legal_hold_active` becomes false, with the series' `version` incrementing."
    PRD §3.3: "Every access request on the series that sits in `BLOCKED` with
    `legal_hold_blocked` true returns to `SUBMITTED` with `legal_hold_blocked` cleared to
    false, and the series' `blocked_access_request_count` decrements by 1 for each."

    Design: Corner/state_machines/legal_hold_release_restores_series_state_and_unblocks_blocked_request
    """
    fx.set_clock(client, DEFAULT_CLOCK)
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "INTERNAL",
                     "item_label": "PERMITS-1985-2009"}],
        stage="RECEIVED",
        schedule_overrides={"code": "GEN-12", "retention_years": 12,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 72.00},
        series_overrides={"title": "Environmental Permits", "business_unit": "EHS",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 21,
                          "earliest_record_year": 1985,
                          "latest_record_year": 2009},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "R. Nkemdirim",
                             "requester_class": "INTERNAL_BUSINESS",
                             "affiliation": "EHS Compliance",
                             "nda_on_file": False},
        purpose="Verify the 1998 discharge permit conditions.",
    )
    hold = fx.active_hold(
        client, holding.series_id, matter_number="MAT-4410",
        effective_from="2026-08-01T00:00:00Z",
    )
    assert fx.read_request(client, case.request_id)["status"] == "BLOCKED"

    released = ok(client.release_legal_hold(
        hold["id"], f.release_payload("Matter closed; hold lifted."), COUNSEL_A))

    assert_fields(
        released,
        status="RELEASED",
        released_at=DEFAULT_CLOCK_MS,
        release_note="Matter closed; hold lifted.",
    )
    series = fx.read_series(client, holding.series_id)
    assert_fields(
        series,
        disposition_state="ACTIVE",
        legal_hold_active=False,
        blocked_access_request_count=0,
    )
    assert_nulls(series, "pre_hold_disposition_state")
    request = fx.read_request(client, case.request_id)
    assert_fields(request, status="SUBMITTED", legal_hold_blocked=False)


def test_rejecting_an_accession_empties_the_shelves_of_its_unprocessed_items(client):
    """PRD §3.4: "It is declared from `RECEIVED` and from `PROVENANCE_VERIFIED`, stores the
    supplied `rejection_reason`, and moves the accession to the terminal `REJECTED`."
    PRD §3.4: "Every item under the accession still in `UNPROCESSED` moves to the terminal
    `REJECTED_ITEM` with `units_on_shelf` set to 0 — those rows are the sole exemption from the
    unit-conservation identity of §2.10, and they are also excluded from
    `processed_unit_count`."

    Design: Corner/state_machines/accession_reject_moves_unprocessed_items_to_rejected_item_with_zero_shelf_units
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 3, "condition_grade": "FAIR", "item_label": "BR114-A"},
            {"unit_count": 2, "condition_grade": "POOR", "item_label": "BR114-B"},
        ],
        stage="RECEIVED",
        schedule_overrides={"code": "GEN-13", "retention_years": 13,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 87.00},
        series_overrides={"title": "Branch Office Files",
                          "business_unit": "Retail Operations",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 55,
                          "earliest_record_year": 1979,
                          "latest_record_year": 2006},
        accession_overrides={"donor_name": "Branch 114"},
    )
    reason = "Duplicates of records already held; no archival value."

    rejected = ok(client.reject_accession(
        holding.accession_id, f.reject_accession_payload(reason), DIRECTOR_A))

    assert_fields(
        rejected, status="REJECTED", rejection_reason=reason, processed_unit_count=0
    )
    for item_id in holding.item_ids:
        item = fx.read_item(client, item_id)
        assert_fields(item, status="REJECTED_ITEM", units_on_shelf=0)


def test_the_activation_cascade_passes_over_a_request_already_closed(client):
    """PRD §3.3: "Hop two blocks the series' live access requests."
    PRD §3.3: "Every access request whose `record_series_id` is the suspended series and whose
    status is `SUBMITTED`, `SCREENING` or `CHANGES_REQUESTED` moves to `BLOCKED` with
    `legal_hold_blocked` set true, and each such move increments the series'
    `blocked_access_request_count` by 1."
    PRD §3.3: "The number of requests moved is stamped onto the hold as
    `suspended_access_request_count`."
    PRD §3.7: "Closing out is declared from `APPROVED`, from `PARTIALLY_APPROVED` and from
    `DENIED`, and all three land in the terminal `CLOSED`, from which no further transition is
    possible."

    Design: Corner/state_machines/legal_hold_activation_leaves_closed_access_request_untouched
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "CONFIDENTIAL",
                     "item_label": "LR-1976-2002"}],
        stage="RECEIVED",
        schedule_overrides={"code": "GEN-14", "retention_years": 14,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 71.00},
        series_overrides={"title": "Labour Relations Files",
                          "business_unit": "Human Resources",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 27,
                          "earliest_record_year": 1976,
                          "latest_record_year": 2002},
    )
    doomed = fx.screened_case(
        client,
        holding,
        decision="DENY",
        redaction_required=False,
        requester_overrides={"display_name": "T. Halvorsen",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Labour History Institute",
                             "nda_on_file": False},
        purpose="Strike of 1981 correspondence.",
    )
    ok(client.deny_access_request(
        doomed.request_id,
        f.deny_request_payload("Confidential personnel content."),
        OFFICER_B,
    ))
    closed = ok(client.close_access_request(doomed.request_id, OFFICER_A))
    assert closed["status"] == "CLOSED"

    live = fx.make_access_request(
        client,
        holding,
        requester=doomed.requester,
        purpose="Follow-up enquiry on the same series.",
    )
    hold = fx.make_hold(
        client, holding.series_id, matter_number="MAT-5150",
        effective_from="2026-08-01T00:00:00Z",
    )

    activated = ok(client.activate_legal_hold(hold["id"], COUNSEL_A))

    assert_fields(activated, status="ACTIVE", suspended_access_request_count=1)
    assert_fields(
        fx.read_request(client, live.request_id),
        status="BLOCKED",
        legal_hold_blocked=True,
    )
    assert_fields(
        fx.read_request(client, doomed.request_id),
        status="CLOSED",
        legal_hold_blocked=False,
    )
    assert_fields(
        fx.read_series(client, holding.series_id),
        blocked_access_request_count=1,
        disposition_state="SUSPENDED",
    )


def test_finalising_an_appraisal_that_was_never_screened_is_refused(client):
    """PRD §3.2: "Screening is the archivist's own read of the series before the director
    looks at it, and it advances the appraisal `DRAFT → SCREENED`."
    PRD §3.2: "Finalisation is the `ArchivesDirector`'s record of decision and advances the
    appraisal `SCREENED → FINAL`."
    PRD §3.2: "The new row enters `status` `DRAFT`, stamps `appraised_by` from `X-User-ID`,
    and leaves `screening_score`, `final_score`, `recommended_disposition` and
    `superseded_by_appraisal_id` null with `brand_heritage_counted` false."
    PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."

    Design: Corner/state_machines/appraisal_finalize_from_draft_returns_appraisal_state_invalid
    """
    series = fx.make_series(
        client,
        title="Trademark Files",
        business_unit="Legal",
        sensitivity_ceiling="INTERNAL",
        annual_volume_linear_feet=40,
        earliest_record_year=1980,
        latest_record_year=2010,
        schedule_overrides={"code": "GEN-15", "retention_years": 15,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 70.00},
    )
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=5,
        uniqueness_factor=6,
        provenance_verified=False,
    )
    assert appraisal["status"] == "DRAFT"

    failed(
        client.finalize_appraisal(appraisal["id"], DIRECTOR_A),
        ERR_APPRAISAL_STATE_INVALID,
        409,
    )

    reloaded = fx.read_appraisal(client, appraisal["id"])
    assert reloaded["status"] == "DRAFT"
    assert_nulls(reloaded, "screening_score", "final_score", "recommended_disposition")
    reread = fx.read_series(client, series["id"])
    assert reread["disposition_state"] == "ACTIVE"
    assert_nulls(reread, "current_appraisal_id")


def test_the_owner_cannot_revise_a_request_that_is_still_merely_submitted(client):
    """PRD §3.7: "The requester answers a changes-requested screening with a **revision**,
    which is the one operation exclusive to the `Requester` role."
    PRD §3.7: "It is declared only from `CHANGES_REQUESTED`, requires `X-User-ID` to equal the
    request's `requester_id`, and carries a replacement `requested_item_ids` array plus an
    optional replacement `purpose`."
    PRD §3.7: "On success the request returns to `SCREENING`, `revision_round` increments by
    1, `requested_page_count` and `prelim_risk_score` are both recomputed from the revised item
    set, and every screening on the request in `OPEN` or in `COMPLETED` moves to `SUPERSEDED`
    with `superseded_reason` set to `REQUESTER_REVISION`."
    PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."

    Design: Corner/state_machines/access_request_revise_from_submitted_returns_request_state_invalid
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "original_format": "PHOTO",
                     "sensitivity_level": "INTERNAL",
                     "item_label": "PKG-1960-1999"}],
        stage="RECEIVED",
        schedule_overrides={"code": "GEN-16", "retention_years": 16,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 75.00},
        series_overrides={"title": "Packaging Design Archive", "business_unit": "Brand",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 9,
                          "earliest_record_year": 1960,
                          "latest_record_year": 1999},
    )
    requester = fx.make_requester(
        client,
        display_name="S. Bianchi",
        requester_class="MEDIA",
        affiliation="Design Weekly",
        nda_on_file=True,
    )
    owner = make_requester_headers(requester["id"])
    case = fx.make_access_request(
        client,
        holding,
        requester=requester,
        headers=owner,
        purpose="Feature on mid-century packaging.",
    )

    failed(
        client.revise_access_request(
            case.request_id,
            f.revise_payload([holding.item_id], purpose="Narrowed to 1968 only."),
            owner,
        ),
        ERR_REQUEST_STATE_INVALID,
        409,
    )

    assert_fields(
        fx.read_request(client, case.request_id),
        status="SUBMITTED",
        revision_round=0,
        purpose="Feature on mid-century packaging.",
    )


def test_a_closed_preservation_plan_cannot_be_closed_a_second_time(client):
    """PRD §3.6: "Closing a plan is declared from `ACTIVE` and from `SATISFIED`, and both
    paths carry the identical additional condition: no migration job on the plan may still be
    in `PENDING_APPROVAL`, `APPROVED` or `IN_PROGRESS`."
    PRD §3.6: "`CLOSED` is terminal."
    PRD §3.6: "The plan is created in `status` `DRAFT` with `budget_committed_cents`,
    `budget_spent_cents` and `at_risk_unit_count` all 0 and `satisfied_at` null."
    PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."

    Design: Corner/state_machines/preservation_plan_close_from_closed_returns_plan_state_invalid
    """
    zone = fx.make_zone(
        client,
        zone_code="Z-PLAN",
        temperature_c=15.0,
        relative_humidity_pct=38.0,
        max_overlapping_migration_jobs=2,
    )
    plan = fx.make_plan(
        client, zone["id"], plan_name="Cold Vault Stabilisation", budget_cents=250000
    )
    first = ok(client.close_preservation_plan(plan["id"], PRESERV_A))
    assert first["status"] == "CLOSED"

    failed(
        client.close_preservation_plan(plan["id"], PRESERV_A),
        ERR_PLAN_STATE_INVALID,
        409,
    )

    assert_fields(
        fx.read_plan(client, plan["id"]),
        status="CLOSED",
        budget_committed_cents=0,
        budget_spent_cents=0,
    )


def test_processing_an_accession_twice_does_not_re_run_the_item_cascade(client):
    """PRD §3.4: "Processing advances the accession `PROVENANCE_VERIFIED → PROCESSED`, and
    every item under that accession still in `UNPROCESSED` moves to `ACCESSIONED` with
    `units_on_shelf` set to `unit_count`, `units_on_loan` set to 0, `units_deaccessioned` set to
    0 and `preservation_format` set to `original_format`."
    PRD §2.6: "12. **State guard** — the target row must be in a state from which the
    requested transition is declared in §3."

    Design: Corner/state_machines/accession_process_twice_returns_accession_state_invalid_on_second_call
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "item_label": "QA-1983-2011"}],
        schedule_overrides={"code": "GEN-17", "retention_years": 17,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 83.00},
        series_overrides={"title": "Quality Assurance Records",
                          "business_unit": "Quality",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 19,
                          "earliest_record_year": 1983,
                          "latest_record_year": 2011},
    )

    failed(
        client.process_accession(holding.accession_id, ARCHIVIST_A),
        ERR_ACCESSION_STATE_INVALID,
        409,
    )

    assert fx.read_accession(client, holding.accession_id)["status"] == "PROCESSED"
    assert_fields(
        fx.read_item(client, holding.item_id),
        status="ACCESSIONED",
        units_on_shelf=3,
        unit_count=3,
    )


def test_re_activating_the_same_hold_is_a_hold_state_error_and_moves_no_series(client):
    """PRD §3.3: "Activation is where the freeze bites, and it is declared only from `DRAFT` —
    any other status yields `ERR_HOLD_STATE_INVALID`."
    PRD §3.3: "Activation additionally requires that no other hold on the same series is
    already `ACTIVE`; a second concurrent hold is refused with `ERR_SERIES_ALREADY_ON_HOLD`."
    PRD §2.4: "All resources except one also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is
    created and increments by exactly 1 on every mutation of that row — including mutations the
    server performs on its own initiative as part of a cascade, and including mutations that
    only touch derived counters."

    Design: Corner/state_machines/legal_hold_activate_twice_returns_hold_state_invalid_on_second_call
    """
    series = fx.make_series(
        client,
        title="Insurance Claims",
        business_unit="Risk",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=35,
        earliest_record_year=1987,
        latest_record_year=2013,
        schedule_overrides={"code": "GEN-18", "retention_years": 18,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
    )
    hold = fx.active_hold(
        client, series["id"], matter_number="MAT-6620",
        effective_from="2026-08-01T00:00:00Z",
    )
    version_after_activation = fx.read_series(client, series["id"])["version"]

    failed(
        client.activate_legal_hold(hold["id"], COUNSEL_A),
        ERR_HOLD_STATE_INVALID,
        409,
    )

    assert_fields(
        fx.read_hold(client, hold["id"]),
        status="ACTIVE",
        suspended_access_request_count=0,
    )
    assert_fields(
        fx.read_series(client, series["id"]),
        disposition_state="SUSPENDED",
        version=version_after_activation,
    )


def test_suspending_an_already_suspended_requester_keeps_the_first_reason(client):
    """PRD §3.7: "Suspension is declared only from `ACTIVE`, stores the supplied
    `suspend_reason`, and moves the requester to `SUSPENDED`; suspending an already-suspended
    requester yields `ERR_REQUESTER_STATE_INVALID`."
    PRD §3.7: "The requester is created in `status` `ACTIVE` with `suspend_reason` null."

    Design: Corner/state_machines/requester_suspend_twice_returns_requester_state_invalid
    """
    requester = fx.make_requester(
        client,
        display_name="D. Farkas",
        requester_class="MEDIA",
        affiliation="Trade Press",
        nda_on_file=False,
    )
    ok(client.suspend_requester(
        requester["id"],
        f.suspend_requester_payload("Breach of reading-room rules."),
        OFFICER_A,
    ))

    failed(
        client.suspend_requester(
            requester["id"],
            f.suspend_requester_payload("Second attempt with a different note."),
            OFFICER_B,
        ),
        ERR_REQUESTER_STATE_INVALID,
        409,
    )

    assert_fields(
        fx.read_requester(client, requester["id"]),
        status="SUSPENDED",
        suspend_reason="Breach of reading-room rules.",
    )
