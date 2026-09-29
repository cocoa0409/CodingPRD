"""Validation rules: violations mapped to codes, and the ladder's fixed order."""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    DIRECTOR_A,
    DIRECTOR_B,
    OFFICER_A,
    OFFICER_B,
    PRESERV_A,
    PRESERV_B,
    assert_empty,
    assert_fields,
    assert_money_cents,
    assert_nulls,
    assert_one_decimal,
    assert_score_2dp,
    assert_total_count,
    factories as f,
    failed,
    fixtures as fx,
    make_requester_headers,
    ok,
    setup,
)
from test_helpers.api_errors import (
    ERR_CONSENT_NOT_SIGNED,
    ERR_DUPLICATE_RESOURCE_KEY,
    ERR_EMBARGO_ACTIVE,
    ERR_FINDING_AID_NOT_PUBLISHED,
    ERR_HERITAGE_CLEARANCE_MISSING,
    ERR_INSUFFICIENT_SHELF_UNITS,
    ERR_ITEM_NOT_IN_SERIES,
    ERR_LEGAL_CLEARANCE_MISSING,
    ERR_LOAN_WINDOW_NOT_OPEN,
    ERR_NO_ITEMS_REQUESTED,
    ERR_NOT_REQUEST_OWNER,
    ERR_PROVENANCE_NOT_DOCUMENTED,
    ERR_RECIPIENT_REPOSITORY_REQUIRED,
    ERR_REQUESTER_SUSPENDED,
    ERR_SCREENING_DECISION_MISSING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SERIES_ALREADY_ON_HOLD,
    ERR_SERIES_PERMANENT,
    ERR_UNIT_COUNT_MISMATCH,
)


def test_processing_an_accession_whose_containers_undercount_the_declaration_is_refused(
    client,
):
    """PRD §2.6: "24. **Declared units reconciled** — `processed_unit_count` must equal
    `declared_unit_count`."
    PRD §3.4: "That figure is the gate on processing: the accession may be closed out only when
    `processed_unit_count` exactly equals `declared_unit_count`, and a mismatch in either
    direction is rejected with `ERR_UNIT_COUNT_MISMATCH`."
    PRD §3.4: "Creating an item forces the parent accession to recompute
    `processed_unit_count`, which is the sum of `unit_count` over all items under that accession
    whose status is anything other than `REJECTED_ITEM`."
    PRD §3.4: "Processing advances the accession `PROVENANCE_VERIFIED → PROCESSED`, and every
    item under that accession still in `UNPROCESSED` moves to `ACCESSIONED` with `units_on_shelf`
    set to `unit_count`, `units_on_loan` set to 0, `units_deaccessioned` set to 0 and
    `preservation_format` set to `original_format`."

    Design: Corner/validations/validations_process_with_unit_count_mismatch_returns_unit_count_mismatch
    """
    holding = fx.make_holding(
        client,
        stage="PROVENANCE_VERIFIED",
        declared_unit_count=4,
        item_specs=[{"unit_count": 3, "item_label": "FAC-1990-2012"}],
        schedule_overrides={"code": "VAL-01", "retention_years": 10,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Facilities Files", "business_unit": "Facilities",
                          "annual_volume_linear_feet": 14,
                          "earliest_record_year": 1990,
                          "latest_record_year": 2012},
    )

    failed(
        client.process_accession(holding.accession_id, ARCHIVIST_A),
        ERR_UNIT_COUNT_MISMATCH,
        422,
    )

    assert_fields(
        fx.read_accession(client, holding.accession_id),
        status="PROVENANCE_VERIFIED",
        processed_unit_count=3,
        declared_unit_count=4,
    )
    assert fx.read_item(client, holding.item_id)["status"] == "UNPROCESSED"


def test_processing_a_received_accession_names_the_provenance_gap_not_the_state(client):
    """PRD §2.6: "11. **Provenance documented** — an accession may be processed only once
    `provenance_documented` is true."
    PRD §2.6: "This too sits ahead of the generic state guard, so that processing an accession
    still in `RECEIVED` names the undocumented provenance rather than a generic state error."
    PRD §2.6: "Rules are therefore evaluated in a fixed ladder, and the **first** rule that
    fails determines the response."
    PRD §3.4: "Processing also requires `provenance_documented` to be true, and because the
    provenance rule sits ahead of the state guard in the ladder, an attempt to process an
    accession still in `RECEIVED` reports `ERR_PROVENANCE_NOT_DOCUMENTED` rather than a state
    error."

    Design: Corner/validations/validations_process_from_received_returns_provenance_not_documented_ahead_of_state_guard
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[{"unit_count": 2, "item_label": "FLEET-1991-2010"}],
        schedule_overrides={"code": "VAL-02", "retention_years": 11,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Fleet Maintenance Files",
                          "business_unit": "Logistics",
                          "annual_volume_linear_feet": 16,
                          "earliest_record_year": 1991,
                          "latest_record_year": 2010},
    )

    failed(
        client.process_accession(holding.accession_id, ARCHIVIST_A),
        ERR_PROVENANCE_NOT_DOCUMENTED,
        422,
    )

    accession = fx.read_accession(client, holding.accession_id)
    assert accession["status"] == "RECEIVED"
    assert accession["provenance_documented"] is False
    assert fx.read_item(client, holding.item_id)["status"] == "UNPROCESSED"


def test_an_empty_item_array_is_a_business_rejection_and_not_a_shape_error(client):
    """PRD §2.6: "21. **Non-empty item set** — `requested_item_ids` must contain at least one
    element."
    PRD §2.6: "An empty array is well-formed shape, so it survives rung 3 and is caught here as
    a business rejection."
    PRD §2.6: "3. **Payload shape** — every required body field present, every enum value a
    declared member of its set, every integer and number inside the range declared for it in §3,
    `requested_item_ids` and `evidence_item_ids` free of duplicate elements, and, on every
    windowed create, `window_end` strictly later than `window_start`."

    Design: Corner/validations/validations_access_request_with_empty_item_array_returns_no_items_requested
    """
    series = fx.make_series(
        client,
        schedule_overrides={"code": "VAL-03", "retention_years": 12,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        title="Union Agreements",
        business_unit="Human Resources",
        annual_volume_linear_feet=7,
        earliest_record_year=1974,
        latest_record_year=2001,
    )
    requester = fx.make_requester(
        client,
        display_name="P. Achterberg",
        requester_class="EXTERNAL_RESEARCHER",
        affiliation="Institute of Labour Studies",
        nda_on_file=False,
    )

    failed(
        client.create_access_request(
            f.access_request_payload(
                requester["id"], series["id"], [], purpose="Nothing specific yet."
            ),
            OFFICER_A,
        ),
        ERR_NO_ITEMS_REQUESTED,
        422,
    )

    assert_empty(
        client.list_access_requests(OFFICER_A, {"record_series_id": series["id"]})
    )


def test_requesting_an_item_that_belongs_to_another_series_is_refused(client):
    """PRD §2.6: "22. **Requested items belong to the series** — every archival item named in
    `requested_item_ids` must sit under an accession whose `record_series_id` equals the
    request's `record_series_id`."
    PRD §2.6: "5. **Reference resolution** — every identifier in the request body that points at
    another resource must resolve."
    PRD §2.6: "Individual elements of `requested_item_ids` and `evidence_item_ids` that name no
    existing item are reported as `ERR_ARCHIVAL_ITEM_NOT_FOUND`."

    Design: Corner/validations/validations_access_request_with_item_from_another_series_returns_item_not_in_series
    """
    schedule = fx.make_schedule(
        client, code="VAL-04", retention_years=13, disposition_action="REVIEW",
        min_appraisal_score_for_permanent=80.00,
    )
    series_a = fx.make_series(
        client, schedule["id"], title="Series A Advertising", business_unit="Marketing",
        annual_volume_linear_feet=10, earliest_record_year=1970,
        latest_record_year=2000,
    )
    holding_b = fx.make_holding(
        client,
        schedule=schedule,
        item_specs=[{"unit_count": 1, "item_label": "SPONSOR-1975"}],
        series_overrides={"title": "Series B Sponsorships",
                          "business_unit": "Marketing",
                          "annual_volume_linear_feet": 11,
                          "earliest_record_year": 1975,
                          "latest_record_year": 2002},
    )
    requester = fx.make_requester(
        client,
        display_name="L. Sørensen",
        requester_class="EXTERNAL_RESEARCHER",
        affiliation="Advertising History Archive",
        nda_on_file=False,
    )

    failed(
        client.create_access_request(
            f.access_request_payload(
                requester["id"], series_a["id"], [holding_b.item_id],
                purpose="Cross-series enquiry.",
            ),
            OFFICER_A,
        ),
        ERR_ITEM_NOT_IN_SERIES,
        422,
    )

    assert_empty(
        client.list_access_requests(OFFICER_A, {"record_series_id": series_a["id"]})
    )


def test_a_suspension_landing_after_filing_blocks_the_officer_s_screening(client):
    """PRD §2.6: "25. **Requester in good standing** — the request's requester must be in
    `ACTIVE` status."
    PRD §3.7: "Both paths require the governing series not to be `SUSPENDED` and the requester
    to be in `ACTIVE` status."
    PRD §3.7: "From `SUBMITTED` the request advances to `SCREENING`, and the previously stamped
    `prelim_risk_score` is retained untouched — no calculation runs."

    Design: Corner/validations/validations_begin_screening_for_suspended_requester_returns_requester_suspended
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 1, "condition_grade": "FAIR",
                     "item_label": "FOUNDER-LETTERS"}],
        schedule_overrides={"code": "VAL-05", "retention_years": 14,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Founders Correspondence",
                          "business_unit": "Corporate Secretary",
                          "annual_volume_linear_feet": 4,
                          "earliest_record_year": 1922,
                          "latest_record_year": 1968},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
        zone_overrides={"temperature_c": 15.0, "relative_humidity_pct": 40.0},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "N. Abubakar",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Business School",
                             "nda_on_file": False},
        purpose="Founder correspondence 1922-1930.",
    )
    setup(client.suspend_requester(
        case.requester_id,
        f.suspend_requester_payload(reason="Unreturned reading-room material."),
        OFFICER_A,
    ))

    failed(
        client.begin_screening(case.request_id, OFFICER_A),
        ERR_REQUESTER_SUSPENDED,
        409,
    )

    assert fx.read_request(client, case.request_id)["status"] == "SUBMITTED"
    assert fx.read_requester(client, case.requester_id)["status"] == "SUSPENDED"


def test_an_open_screening_carries_no_decision_so_approval_is_refused(client):
    """PRD §2.6: "26. **Screening decision available** — the request's `current_screening_id`
    must resolve to a screening in `COMPLETED` status whose `decision` is `GRANT_FULL` for a
    `FULL` approval, or one of `GRANT_FULL` or `GRANT_REDACTED` for a `REDACTED` approval."
    PRD §3.7: "The new screening stamps `screened_by` from `X-User-ID` and
    `max_item_sensitivity` — the highest `sensitivity_level` across the request's requested
    items, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` or `RESTRICTED` — and enters `status`
    `OPEN` with `redaction_required` false, and `decision`, `screening_note`,
    `superseded_reason` and `completed_at` all null."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."

    Design: Corner/validations/validations_approve_with_screening_still_open_returns_screening_decision_missing
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "original_format": "PHOTO",
                     "item_label": "PLANT-PHOTOS"}],
        schedule_overrides={"code": "VAL-06", "retention_years": 15,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Plant Photographs",
                          "business_unit": "Manufacturing",
                          "annual_volume_linear_feet": 13,
                          "earliest_record_year": 1958,
                          "latest_record_year": 1996},
    )
    case = fx.make_access_request(
        client,
        holding,
        requester_overrides={"display_name": "G. Marchetti",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Industrial Heritage Trust",
                             "nda_on_file": False},
        purpose="Plant expansion of 1961.",
    )
    fx.drive_to_screening(client, case)
    fx.open_screening(client, case)

    failed(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        ),
        ERR_SCREENING_DECISION_MISSING,
        422,
    )

    request = fx.read_request(client, case.request_id)
    assert request["status"] == "SCREENING"
    assert_nulls(request, "service_fee_cents", "post_screen_risk_score")
    assert fx.read_screening(client, case.screening_id)["status"] == "OPEN"


def test_a_requester_may_not_file_on_a_colleague_s_behalf(client):
    """PRD §2.6: "7. **Requester ownership** — when the acting role is `Requester`, `X-User-ID`
    must equal the `requester_id` in the body on a create, or the target request's
    `requester_id` on a revision."
    PRD §2.6: "2. **Role authorisation** — the presented role appears in the called endpoint's
    authorised list."
    PRD §2.6: "Failure: `ERR_NOT_REQUEST_OWNER` (403)."

    Design: Corner/validations/validations_requester_filing_for_another_requester_returns_not_request_owner
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 1, "sensitivity_level": "PUBLIC",
                     "item_label": "BROCHURES-1962"}],
        schedule_overrides={"code": "VAL-12", "retention_years": 21,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Sales Brochures", "business_unit": "Marketing",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1962,
                          "latest_record_year": 1994},
    )
    requester_a = fx.make_requester(
        client, display_name="A. Ferreira", requester_class="EXTERNAL_RESEARCHER",
        affiliation="Design Museum", nda_on_file=False,
    )
    requester_b = fx.make_requester(
        client, display_name="B. Whitfield", requester_class="EXTERNAL_RESEARCHER",
        affiliation="Design Museum", nda_on_file=False,
    )

    failed(
        client.create_access_request(
            f.access_request_payload(
                requester_b["id"], holding.series_id, [holding.item_id],
                purpose="Filing on a colleague's behalf.",
            ),
            make_requester_headers(requester_a["id"]),
        ),
        ERR_NOT_REQUEST_OWNER,
        403,
    )

    assert_empty(
        client.list_access_requests(OFFICER_A, {"requester_id": requester_b["id"]})
    )


def test_a_future_embargo_holds_the_approved_transcript_back(client):
    """PRD §2.6: "18. **Embargo elapsed** — the interview's `embargo_until` must be null, or the
    logical clock must be at or after it."
    PRD §3.8: "Approving moves it `REVIEWED → APPROVED` and is the single point where the two
    axes interact: approval additionally requires `consent_status` to be exactly `SIGNED`,
    refusing otherwise with `ERR_CONSENT_NOT_SIGNED`, and requires `embargo_until` to be null or
    the logical clock to stand at or after it, refusing otherwise with `ERR_EMBARGO_ACTIVE`."
    PRD §3.8: "When consent is `SIGNED`, the release state is `PUBLIC` if transcription has
    reached `APPROVED` **and** either there is no embargo or the logical clock stands at or after
    `embargo_until`; failing that, it is `RESEARCH_ROOM_ONLY` if transcription has reached
    `REVIEWED` or `APPROVED`; and `WITHHELD` in every remaining case."

    Design: Corner/validations/validations_transcript_approve_under_future_embargo_returns_embargo_active
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[],
        declared_unit_count=1,
        schedule_overrides={"code": "VAL-07", "retention_years": 16,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Oral History Programme",
                          "business_unit": "Corporate Archives",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 3,
                          "earliest_record_year": 2001,
                          "latest_record_year": 2020},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )
    interview = fx.interview_at(
        client,
        holding.accession_id,
        consent_actions=["SIGN"],
        transcription_actions=["START_DRAFT", "MARK_REVIEWED"],
        narrator_name="E. Vasquez",
        interview_date="2026-07-15T14:00:00Z",
        embargo_until="2027-01-01T00:00:00Z",
    )

    failed(
        client.interview_transcription(
            interview["id"], f.transcription_payload("APPROVE"), ARCHIVIST_A
        ),
        ERR_EMBARGO_ACTIVE,
        409,
    )

    assert_fields(
        fx.read_interview(client, interview["id"]),
        transcription_status="REVIEWED",
        consent_status="SIGNED",
        release_state="RESEARCH_ROOM_ONLY",
    )


def test_unsigned_consent_is_reported_ahead_of_the_embargo(client):
    """PRD §2.6: "17. **Consent signed** — a transcript may be approved only when the
    interview's `consent_status` is `SIGNED`."
    PRD §2.6: "Note the ordering against rung 17: an interview that is both unconsented and
    embargoed reports the consent failure."
    PRD §3.8: "The consent check is evaluated before the embargo check, so an interview that is
    both unconsented and still embargoed reports the consent failure."
    PRD §3.8: "When consent is `WITHDRAWN`, or still `PENDING`, the release state is `WITHHELD`
    regardless of transcription."

    Design: Corner/validations/validations_transcript_approve_with_consent_pending_beats_embargo_check
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[],
        declared_unit_count=1,
        schedule_overrides={"code": "VAL-08", "retention_years": 17,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Shop Floor Voices",
                          "business_unit": "Corporate Archives",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 2,
                          "earliest_record_year": 2005,
                          "latest_record_year": 2021},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )
    interview = fx.interview_at(
        client,
        holding.accession_id,
        transcription_actions=["START_DRAFT", "MARK_REVIEWED"],
        narrator_name="H. Lindqvist",
        interview_date="2026-07-20T09:30:00Z",
        embargo_until="2027-01-01T00:00:00Z",
    )

    failed(
        client.interview_transcription(
            interview["id"], f.transcription_payload("APPROVE"), ARCHIVIST_A
        ),
        ERR_CONSENT_NOT_SIGNED,
        422,
    )

    assert_fields(
        fx.read_interview(client, interview["id"]),
        consent_status="PENDING",
        transcription_status="REVIEWED",
        release_state="WITHHELD",
    )


def test_a_donation_proposal_must_name_the_receiving_repository(client):
    """PRD §2.6: "27. **Donation recipient named** — a proposal whose `route` is `DONATION` must
    carry a non-empty `recipient_repository`."
    PRD §2.6: "Applies to `POST /deaccession-proposals` and
    `POST /deaccession-proposals/{id}/approve`."
    PRD §2.6: "Failure: `ERR_RECIPIENT_REPOSITORY_REQUIRED` (422)."

    Design: Corner/validations/validations_donation_proposal_without_recipient_repository_returns_recipient_repository_required
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 6, "sensitivity_level": "PUBLIC",
                     "item_label": "DUPES-1981-2004"}],
        schedule_overrides={"code": "VAL-09", "retention_years": 18,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 90.00},
        series_overrides={"title": "Duplicate Publications", "business_unit": "Library",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 20,
                          "earliest_record_year": 1981,
                          "latest_record_year": 2004},
    )

    failed(
        client.create_deaccession_proposal(
            f.deaccession_proposal_payload(
                holding.item_id, units=6, route="DONATION",
                rationale="Offer duplicates to a university library.",
            ),
            ARCHIVIST_A,
        ),
        ERR_RECIPIENT_REPOSITORY_REQUIRED,
        422,
    )

    assert_empty(
        client.list_deaccession_proposals(
            ARCHIVIST_A, {"archival_item_id": holding.item_id}
        )
    )
    assert_fields(
        fx.read_item(client, holding.item_id), status="ACCESSIONED", units_on_shelf=6
    )


def test_confirmation_is_refused_when_the_loan_asks_for_more_units_than_are_shelved(
    client,
):
    """PRD §2.6: "30. **Sufficient shelved units** — the item's `units_on_shelf` must be at
    least the number of units the operation moves."
    PRD §3.8: "It requires the item to be in `ACCESSIONED` status, the item's `condition_grade`
    to be `GOOD` or `FAIR` — `POOR` and `UNSTABLE` material may not go on display, and the
    attempt is refused with `ERR_ITEM_CONDITION_UNSUITABLE` — and the item's `units_on_shelf` to
    be at least the loan's `units`, refusing otherwise with `ERR_INSUFFICIENT_SHELF_UNITS`."
    PRD §3.8: "No units move at confirmation."

    Design: Corner/validations/validations_loan_confirm_over_units_on_shelf_returns_insufficient_shelf_units
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 4, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC", "item_label": "MUSEUM-OBJECTS"}],
        schedule_overrides={"code": "VAL-10", "retention_years": 19,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Company Museum Objects", "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 5,
                          "earliest_record_year": 1930,
                          "latest_record_year": 1975},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-08-05T00:00:00Z",
        "2026-09-05T00:00:00Z",
        units=5,
        exhibit_name="Centenary Gallery",
    )

    failed(
        client.confirm_exhibit_loan(loan["id"], PRESERV_A),
        ERR_INSUFFICIENT_SHELF_UNITS,
        422,
    )

    assert fx.read_loan(client, loan["id"])["status"] == "REQUESTED"
    assert_fields(
        fx.read_item(client, holding.item_id),
        status="ACCESSIONED",
        units_on_shelf=4,
        units_on_loan=0,
    )


def test_material_cannot_leave_the_shelf_before_its_display_window_opens(client):
    """PRD §2.6: "20. **Display window open** — the logical clock must be at or after the loan's
    `window_start`."
    PRD §3.8: "Check-out is the `Archivist`'s physical release, declared only from `CONFIRMED`."
    PRD §3.8: "It requires `units_on_shelf` to be at least the loan's `units`, and requires the
    logical clock to stand at or after the loan's `window_start`, refusing otherwise with
    `ERR_LOAN_WINDOW_NOT_OPEN`."
    PRD §3.8: "On success the loan moves to `OUT`, `checked_out_at` is stamped from the logical
    clock, and the item moves `ACCESSIONED → ON_LOAN` with the loan's `units` subtracted from
    `units_on_shelf` and the same number added to `units_on_loan`, preserving the conservation
    identity of §2.10 exactly."

    Design: Corner/validations/validations_check_out_before_window_start_returns_loan_window_not_open
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC", "item_label": "EXHIBIT-OBJECTS"}],
        schedule_overrides={"code": "VAL-11", "retention_years": 20,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Exhibit Ready Objects", "business_unit": "Heritage",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 4,
                          "earliest_record_year": 1940,
                          "latest_record_year": 1985},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        stage="CONFIRMED",
        units=2,
        exhibit_name="Autumn Showcase",
    )

    failed(
        client.check_out_exhibit_loan(loan["id"], ARCHIVIST_A),
        ERR_LOAN_WINDOW_NOT_OPEN,
        422,
    )

    reloaded = fx.read_loan(client, loan["id"])
    assert reloaded["status"] == "CONFIRMED"
    assert_nulls(reloaded, "checked_out_at")
    assert_fields(
        fx.read_item(client, holding.item_id), status="ACCESSIONED", units_on_shelf=2
    )


def test_a_second_zone_cannot_reuse_an_existing_zone_code(client):
    """PRD §2.6: "6. **Business-key uniqueness** — a retention schedule's `code`, a legal hold's
    `matter_number` and a storage zone's `zone_code` must each be unique across all existing
    rows of their type."
    PRD §2.6: "Failure: `ERR_DUPLICATE_RESOURCE_KEY` (409)."
    PRD §2.11: "The derivation is re-run from scratch on the reading supplied at zone creation
    and again on every subsequent reading, and it reads nothing but that single latest pair —
    historical readings are not retained, only counted, in `reading_count`."

    Design: Corner/validations/validations_duplicate_zone_code_returns_duplicate_resource_key
    """
    zone = fx.make_zone(
        client, zone_code="Z-DUP", temperature_c=16.0, relative_humidity_pct=44.0,
        max_overlapping_migration_jobs=1,
    )

    failed(
        client.create_storage_zone(
            f.storage_zone_payload(12.0, 35.0, 3, zone_code="Z-DUP"), PRESERV_B
        ),
        ERR_DUPLICATE_RESOURCE_KEY,
        409,
    )

    stored = fx.read_zone(client, zone["id"])
    assert_one_decimal(stored, "temperature_c", 16.0)
    assert stored["max_overlapping_migration_jobs"] == 1
    assert_total_count(client.list_storage_zones(PRESERV_A), 1)


def test_a_second_hold_cannot_be_activated_over_an_already_frozen_series(client):
    """PRD §2.6: "13. **Single active hold per series** — a hold may not be activated while a
    different hold on the same series is already `ACTIVE`."
    PRD §3.3: "Activation additionally requires that no other hold on the same series is already
    `ACTIVE`; a second concurrent hold is refused with `ERR_SERIES_ALREADY_ON_HOLD`."
    PRD §3.3: "Whichever of `ACTIVE`, `ELIGIBLE_FOR_DISPOSITION` or `PERMANENT` the series
    currently occupies is copied verbatim into `pre_hold_disposition_state`, the series moves to
    `SUSPENDED`, `legal_hold_active` is set true, and the series' `version` increments with
    `updated_at` refreshed."

    Design: Corner/validations/validations_second_hold_activation_on_same_series_returns_series_already_on_hold
    """
    series = fx.make_series(
        client,
        schedule_overrides={"code": "VAL-13", "retention_years": 22,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        title="Patent Prosecution Files",
        business_unit="Legal",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=18,
        earliest_record_year=1984,
        latest_record_year=2014,
    )
    hold_a = fx.make_hold(
        client, series["id"], matter_number="MAT-7001",
        effective_from="2026-08-01T00:00:00Z",
    )
    hold_b = fx.make_hold(
        client, series["id"], matter_number="MAT-7002",
        effective_from="2026-08-01T00:00:00Z",
    )
    setup(client.activate_legal_hold(hold_a["id"], COUNSEL_A))

    failed(
        client.activate_legal_hold(hold_b["id"], COUNSEL_A),
        ERR_SERIES_ALREADY_ON_HOLD,
        409,
    )

    assert fx.read_hold(client, hold_b["id"])["status"] == "DRAFT"
    assert fx.read_hold(client, hold_a["id"])["status"] == "ACTIVE"
    assert_fields(
        fx.read_series(client, series["id"]),
        disposition_state="SUSPENDED",
        pre_hold_disposition_state="ACTIVE",
    )


def test_legal_clearance_is_refused_once_an_appraisal_has_made_the_series_permanent(
    client,
):
    """PRD §2.6: "16. **Series not permanent** — the governing series must not be in `PERMANENT`
    disposition state, because permanently designated heritage records may neither be cleared for
    removal nor disposed."
    PRD §3.9: "Both paths require the item's governing series to have `legal_hold_active` false
    and to be in neither `SUSPENDED` disposition state, refusing otherwise with
    `ERR_SERIES_DISPOSITION_SUSPENDED`, nor `PERMANENT`, refusing otherwise with
    `ERR_SERIES_PERMANENT`."
    PRD §3.2: "When the rounded `final_score` is greater than or equal to the governing
    schedule's `min_appraisal_score_for_permanent`, `recommended_disposition` is `PERMANENT`;
    otherwise it is the schedule's `disposition_action`, so one of `DESTROY`, `REVIEW` or
    `TRANSFER`."
    PRD §3.2: "From `ACTIVE`, a recommendation of `PERMANENT` moves the series to `PERMANENT`."

    Design: Corner/validations/validations_legal_clearance_on_permanent_series_returns_series_permanent
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "item_label": "CHARTER-RECORDS"}],
        schedule_overrides={"code": "VAL-14", "retention_years": 23,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 50.00},
        series_overrides={"title": "Founding Charter Records",
                          "business_unit": "Corporate Secretary",
                          "annual_volume_linear_feet": 40,
                          "earliest_record_year": 1980,
                          "latest_record_year": 2010},
    )
    appraisal = fx.finalized_appraisal(
        client,
        holding.series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=5,
        uniqueness_factor=6,
        provenance_verified=True,
    )
    proposal = fx.make_proposal(
        client, holding.item_id, units=3, rationale="Space recovery in the vault."
    )

    failed(client.legal_clearance(proposal["id"], COUNSEL_A), ERR_SERIES_PERMANENT, 409)

    assert fx.read_series(client, holding.series_id)["disposition_state"] == "PERMANENT"
    reloaded = fx.read_appraisal(client, appraisal["id"])
    assert_score_2dp(reloaded, "final_score", 63.00)
    assert reloaded["recommended_disposition"] == "PERMANENT"
    stored = fx.read_proposal(client, proposal["id"])
    assert stored["status"] == "SUBMITTED"
    assert_nulls(stored, "legal_cleared_by")


def test_the_officer_who_raised_a_migration_job_may_not_approve_it(client):
    """PRD §2.9: "The officer approving a migration job must present an `X-User-ID` different
    from the job's `requested_by`."
    PRD §2.9: "The comparison is made on `X-User-ID`, and a collision is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.9: "There is no override, and no role that is exempt."
    PRD §2.10: "A preservation plan's `budget_committed_cents` must, after every single request
    including every cascade, equal the exact sum of `committed_cost_cents` over the migration
    jobs on that plan whose status is `APPROVED` or `IN_PROGRESS`."

    Design: Corner/validations/validations_migration_approve_by_requesting_officer_returns_segregation_of_duties
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 10, "item_label": "TRAINING-PAPER"},
                    {"unit_count": 4, "original_format": "FILM",
                     "item_label": "TRAINING-REELS"}],
        schedule_overrides={"code": "VAL-15", "retention_years": 24,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Training Films", "business_unit": "Learning",
                          "annual_volume_linear_feet": 9,
                          "earliest_record_year": 1977,
                          "latest_record_year": 1999},
        zone_overrides={"temperature_c": 15.0, "relative_humidity_pct": 40.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(
        client, holding.zone_id, plan_name="Training Media Refresh", budget_cents=400000
    )
    job = fx.make_job(
        client,
        plan["id"],
        holding.item_id,
        units=10,
        target_format="PRESERVATION_TIFF",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-20T00:00:00Z",
    )

    failed(
        client.approve_migration_job(job["id"], PRESERV_A),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    reloaded = fx.read_job(client, job["id"])
    assert_fields(reloaded, status="PENDING_APPROVAL", requested_by="preserv-a")
    assert_money_cents(reloaded, "committed_cost_cents", 10500)
    assert_money_cents(
        fx.read_plan(client, plan["id"]), "budget_committed_cents", 0
    )


def test_a_redacted_approval_is_permitted_at_a_risk_score_above_the_threshold(client):
    """PRD §2.6: "35. **Redaction required above the risk threshold** — a `FULL` approval
    requires the request's `post_screen_risk_score` to be strictly below the redaction threshold
    of 75; at or above it, only a `REDACTED` scope is permitted."
    PRD §3.7: "On top of that, a `FULL` approval requires `post_screen_risk_score` to be strictly
    below 75; at 75 or above, the only permitted outcome is a `REDACTED` approval, and an attempt
    at full scope is refused with `ERR_RISK_THRESHOLD_REQUIRES_REDACTION`."
    PRD §3.7: "No risk gate applies to the redacted branch."
    PRD §3.7: "The `approval_scope` supplied on an approval determines the destination: `FULL`
    drives `SCREENING → APPROVED`, and `REDACTED` drives `SCREENING → PARTIALLY_APPROVED`."
    PRD §3.7: "Both subtract an NDA credit of 12 points when the requester's `nda_on_file` is
    true, and nothing when it is false."

    Design: Corner/validations/validations_redacted_approval_succeeds_at_post_screen_risk_seventy_eight
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 2, "sensitivity_level": "RESTRICTED",
                     "item_label": "COMMITTEE-PAPERS"}],
        schedule_overrides={"code": "VAL-16", "retention_years": 25,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Board Committee Papers",
                          "business_unit": "Corporate Secretary",
                          "sensitivity_ceiling": "CONFIDENTIAL",
                          "annual_volume_linear_feet": 8,
                          "earliest_record_year": 1969,
                          "latest_record_year": 2005},
        zone_overrides={"relative_humidity_pct": 43.0},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_REDACTED",
        redaction_required=False,
        screening_note="Release with names withheld verbally.",
        requester_overrides={"display_name": "C. Nakamura",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Corporate Governance Review",
                             "nda_on_file": True},
        purpose="Governance practices 1969-1980.",
    )
    assert case.request["prelim_risk_score"] == 53

    approved = ok(client.approve_access_request(
        case.request_id, f.approve_request_payload("REDACTED"), OFFICER_B))

    assert_fields(
        approved,
        status="PARTIALLY_APPROVED",
        post_screen_risk_score=78,
        approval_scope="REDACTED",
        requested_page_count=22,
    )
    assert_money_cents(approved, "service_fee_cents", 3270)


def test_a_proposal_holding_only_heritage_clearance_names_the_missing_legal_one(client):
    """PRD §2.6: "8. **Legal clearance present** — on a deaccession approval,
    `legal_cleared_by` must not be null."
    PRD §2.6: "This sits deliberately *ahead* of the generic state guard at rung 11, so that an
    approval attempted on a proposal that has only heritage clearance names the missing legal
    clearance rather than returning an opaque state error."
    PRD §3.9: "Both `legal_cleared_by` and `heritage_cleared_by` must be non-null — and because
    those two checks sit ahead of the state guard in the ladder, an approval attempted on a
    proposal holding only heritage clearance reports `ERR_LEGAL_CLEARANCE_MISSING` while one
    holding only legal clearance reports `ERR_HERITAGE_CLEARANCE_MISSING`, rather than a generic
    state error."
    PRD §3.9: "It is declared only from `DUALLY_CLEARED`, and it enforces five things."

    Design: Corner/validations/validations_deaccession_approve_from_heritage_cleared_returns_legal_clearance_missing
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 4, "sensitivity_level": "PUBLIC",
                     "item_label": "MANUALS-1988-2007"}],
        schedule_overrides={"code": "VAL-17", "retention_years": 26,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 95.00},
        series_overrides={"title": "Superseded Manuals", "business_unit": "Operations",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 25,
                          "earliest_record_year": 1988,
                          "latest_record_year": 2007},
    )
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        stage="HERITAGE_CLEARED",
        units=4,
        rationale="Superseded content of no archival value.",
    )

    failed(
        client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B),
        ERR_LEGAL_CLEARANCE_MISSING,
        422,
    )

    reloaded = fx.read_proposal(client, proposal["id"])
    assert_fields(
        reloaded, status="HERITAGE_CLEARED", heritage_cleared_by="director-a"
    )
    assert_nulls(reloaded, "legal_cleared_by", "approved_by")
    assert fx.read_item(client, holding.item_id)["status"] == "ACCESSIONED"


def test_a_proposal_holding_only_legal_clearance_names_the_missing_heritage_one(client):
    """PRD §2.6: "9. **Heritage clearance present** — on a deaccession approval,
    `heritage_cleared_by` must not be null."
    PRD §2.6: "This sits after the legal-clearance rung and still ahead of the generic state
    guard, so that an approval attempted on a proposal that has only legal clearance names the
    missing heritage clearance."
    PRD §3.9: "The approving `X-User-ID` must differ from `legal_cleared_by`, or the attempt is
    refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Both paths stamp `legal_cleared_by` from `X-User-ID` and store the optional
    `clearance_note`."

    Design: Corner/validations/validations_deaccession_approve_from_legal_cleared_returns_heritage_clearance_missing
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 5, "sensitivity_level": "PUBLIC",
                     "item_label": "FORMS-1986-2003"}],
        schedule_overrides={"code": "VAL-18", "retention_years": 27,
                            "disposition_action": "DESTROY",
                            "min_appraisal_score_for_permanent": 95.00},
        series_overrides={"title": "Obsolete Forms",
                          "business_unit": "Administration",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 22,
                          "earliest_record_year": 1986,
                          "latest_record_year": 2003},
    )
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        stage="LEGAL_CLEARED",
        units=5,
        rationale="Blank stock with no evidential value.",
    )

    failed(
        client.approve_deaccession_proposal(proposal["id"], DIRECTOR_A),
        ERR_HERITAGE_CLEARANCE_MISSING,
        422,
    )

    reloaded = fx.read_proposal(client, proposal["id"])
    assert_fields(reloaded, status="LEGAL_CLEARED", legal_cleared_by="counsel-a")
    assert_nulls(reloaded, "heritage_cleared_by")
    assert fx.read_item(client, holding.item_id)["status"] == "ACCESSIONED"


def test_an_approval_citing_an_unpublished_finding_aid_is_refused(client):
    """PRD §2.6: "23. **Cited finding aid published** — when a request's `finding_aid_id` is not
    null, the referenced aid must be in `PUBLISHED` status."
    PRD §3.7: "Fourth, the request's `finding_aid_id` must be null or else name an aid in
    `PUBLISHED` status, or `ERR_FINDING_AID_NOT_PUBLISHED`."
    PRD §3.7: "All three are stored, `completed_at` is stamped from the logical clock, and the
    post-screen risk pass runs onto the parent request's `post_screen_risk_score`."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."

    Design: Corner/validations/validations_approve_citing_draft_finding_aid_returns_finding_aid_not_published
    """
    holding = fx.make_holding(
        client,
        stage="RECEIVED",
        item_specs=[{"unit_count": 3, "item_label": "REGION-1981-2009"}],
        schedule_overrides={"code": "VAL-19", "retention_years": 28,
                            "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Regional Office Records",
                          "business_unit": "Retail Operations",
                          "annual_volume_linear_feet": 17,
                          "earliest_record_year": 1981,
                          "latest_record_year": 2009},
    )
    aid = fx.make_finding_aid(
        client,
        holding.accession_id,
        title="Regional Office Records, 1981-2009",
        arrangement_level="SERIES",
        version_label="v0.1",
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        screening_note="Routine business records.",
        finding_aid_id=aid["id"],
        requester_overrides={"display_name": "K. Adeyemi",
                             "requester_class": "EXTERNAL_RESEARCHER",
                             "affiliation": "Regional History Society",
                             "nda_on_file": False},
        purpose="Branch closures of the 1990s.",
    )

    failed(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        ),
        ERR_FINDING_AID_NOT_PUBLISHED,
        422,
    )

    request = fx.read_request(client, case.request_id)
    assert_fields(request, status="SCREENING", post_screen_risk_score=45)
    assert_nulls(request, "service_fee_cents")
    assert fx.read_finding_aid(client, aid["id"])["status"] == "DRAFT"
