"""Role authorisation, authentication and segregation of duties.

Every test here translates one instance of the corner-design ``RBAC`` section:
three exclusive operations refused to a role that owns the row, two header
defects that stop at the authentication rung, one operation genuinely shared by
two roles, and the two ``X-User-ID`` collisions the contract bars.
"""

from test_helpers import (
    ARCHIVIST_A,
    COUNSEL_A,
    COUNSEL_A_ID,
    DIRECTOR_A,
    DIRECTOR_B,
    OFFICER_A,
    OFFICER_A_ID,
    PRESERV_A,
    assert_fields,
    assert_ids_exactly,
    assert_nulls,
    assert_total_count,
    created,
    factories as f,
    failed,
    fixtures as fx,
    headers_without_user_id,
    make_headers,
    make_requester_headers,
    ok,
)
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.types import ROLE_ARCHIVES_DIRECTOR


def test_the_archivist_who_drafted_an_aid_still_may_not_publish_it(client):
    """PRD §2.1: "If both headers are well formed but the presented role is not among the
    roles authorised for the endpoint being called — the authorisation column of the
    endpoint table in §4 is definitive — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.6: "2. **Role authorisation** — the presented role appears in the called
    endpoint's authorised list."
    PRD §3.5: "Publication belongs to the `ArchivesDirector` and is declared only from
    `UNDER_REVIEW`."
    PRD §3.5: "The aid is created in `status` `DRAFT` with `described_item_count` and
    `stale_item_count` both 0, `revision_cycle_count` 0 and `published_at` null."

    Design: Corner/RBAC/rbac_archivist_cannot_publish_finding_aid_returns_unauthorized
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 3, "sensitivity_level": "PUBLIC",
                     "item_label": "PROOFS-BOX-1"}],
        schedule_overrides={"code": "RB-01", "retention_years": 50,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 7.1",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Advertising Proofs",
                          "business_unit": "Marketing",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 7,
                          "earliest_record_year": 1968,
                          "latest_record_year": 1999},
        zone_overrides={"zone_code": "Z-RB01", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    aid = fx.reviewed_finding_aid(
        client,
        holding.accession_id,
        title="Advertising Proofs, 1968-1999",
        arrangement_level="SERIES",
        version_label="v1.0",
    )
    assert aid["status"] == "UNDER_REVIEW"

    failed(
        client.publish_finding_aid(aid["id"], ARCHIVIST_A),
        ERR_UNAUTHORIZED,
        403,
    )

    reloaded = fx.read_finding_aid(client, aid["id"])
    assert_fields(reloaded, status="UNDER_REVIEW", stale_item_count=0)
    assert_nulls(reloaded, "published_at")
    assert fx.read_accession(client, holding.accession_id)["status"] == "PROCESSED"


def test_the_preservation_officer_cannot_create_a_record_series_at_all(client):
    """PRD §2.1: "If both headers are well formed but the presented role is not among the
    roles authorised for the endpoint being called — the authorisation column of the
    endpoint table in §4 is definitive — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.1: "The `Archivist` is the processing archivist: creating series, accessions,
    archival items, finding aids, oral history interviews, deaccession proposals and
    appraisal drafts, submitting aids for review, screening appraisals, and carrying out
    physical custody movements such as exhibit check-out, return and deaccession
    execution."
    PRD §2.1: "The `PreservationOfficer` owns storage zones and their environmental
    readings, preservation plans, the entire migration-job lifecycle, and the conservation
    confirmation of an exhibit loan."
    PRD §2.6: "3. **Payload shape** — every required body field present, every enum value
    a declared member of its set, every integer and number inside the range declared for
    it in §3, `requested_item_ids` and `evidence_item_ids` free of duplicate elements,
    and, on every windowed create, `window_end` strictly later than `window_start`."

    Design: Corner/RBAC/rbac_preservation_officer_cannot_create_record_series_returns_unauthorized
    """
    schedule = fx.make_schedule(
        client,
        code="RB-02",
        retention_years=51,
        disposition_action="REVIEW",
        legal_citation="Corp Policy 7.2",
        min_appraisal_score_for_permanent=80.00,
    )

    failed(
        client.create_record_series(
            f.record_series_payload(
                schedule["id"],
                title="Environmental Logs",
                business_unit="Facilities",
                sensitivity_ceiling="INTERNAL",
                annual_volume_linear_feet=5,
                earliest_record_year=2000,
                latest_record_year=2020,
            ),
            PRESERV_A,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    assert_total_count(client.list_record_series(ARCHIVIST_A), 0)
    assert_total_count(client.list_retention_schedules(DIRECTOR_A), 1)


def test_the_requester_owns_its_request_yet_cannot_move_it_into_screening(client):
    """PRD §2.1: "If both headers are well formed but the presented role is not among the
    roles authorised for the endpoint being called — the authorisation column of the
    endpoint table in §4 is definitive — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §2.6: "7. **Requester ownership** — when the acting role is `Requester`,
    `X-User-ID` must equal the `requester_id` in the body on a create, or the target
    request's `requester_id` on a revision."
    PRD §3.7: "Both passes start from the requester's class weight: 10 points for
    `INTERNAL_BUSINESS`, 30 for `EXTERNAL_RESEARCHER` and 45 for `MEDIA`."
    PRD §3.7: "Both subtract an NDA credit of 12 points when the requester's
    `nda_on_file` is true, and nothing when it is false."

    Design: Corner/RBAC/rbac_requester_cannot_begin_screening_returns_unauthorized
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 1, "sensitivity_level": "PUBLIC",
                     "item_label": "NEWSLETTERS"}],
        schedule_overrides={"code": "RB-03", "retention_years": 52,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 7.3",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Company Newsletters",
                          "business_unit": "Communications",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 3,
                          "earliest_record_year": 1955,
                          "latest_record_year": 2001},
        zone_overrides={"zone_code": "Z-RB03", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    requester = fx.make_requester(
        client,
        display_name="M. Adeyemi",
        requester_class="EXTERNAL_RESEARCHER",
        affiliation="State University",
        nda_on_file=True,
    )
    case = fx.make_access_request(
        client,
        holding,
        requester=requester,
        headers=make_requester_headers(requester["id"]),
        purpose="Dissertation chapter on internal communications.",
    )
    assert case.request["prelim_risk_score"] == 18

    failed(
        client.begin_screening(case.request_id, case.requester_headers),
        ERR_UNAUTHORIZED,
        403,
    )

    reloaded = fx.read_request(client, case.request_id)
    assert_fields(
        reloaded, status="SUBMITTED", requester_id=requester["id"], prelim_risk_score=18
    )


def test_an_unknown_role_and_a_missing_user_id_both_stop_at_authentication(client):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    operator, and `X-User-Role`, declaring the capacity in which that operator acts."
    PRD §2.1: "The system recognises exactly seven roles, spelled here as they must appear
    in the header: `ArchivesDirector`, `Archivist`, `PreservationOfficer`,
    `AccessServicesOfficer`, `LegalCounsel`, `Requester`, and `SystemOperator`."
    PRD §2.1: "If either header is absent, or if `X-User-Role` carries a value outside that
    set of seven, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "1. **Header authentication** — `X-User-ID` and `X-User-Role` present, and
    the role one of the seven declared in §2.1."

    Design: Corner/RBAC/rbac_missing_or_unknown_role_header_returns_unauthenticated
    """
    schedule = fx.make_schedule(
        client,
        code="RB-04",
        retention_years=53,
        disposition_action="REVIEW",
        legal_citation="Corp Policy 7.4",
        min_appraisal_score_for_permanent=80.00,
    )

    failed(
        client.get_retention_schedule(
            schedule["id"], make_headers("intern-a", "HeritageIntern")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    failed(
        client.get_retention_schedule(
            schedule["id"], headers_without_user_id(ROLE_ARCHIVES_DIRECTOR)
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    assert ok(client.get_retention_schedule(schedule["id"], DIRECTOR_A))["code"] == (
        "RB-04"
    )


def test_the_director_and_the_archivist_may_each_open_an_exhibit_loan(client):
    """PRD §3.8: "**Anniversary, museum and exhibit projects** borrow physical units
    through an **exhibit loan**, which either an `ArchivesDirector` or an `Archivist` may
    request."
    PRD §3.8: "The request names the `archival_item_id` wanted for display, an
    `exhibit_name` of 1 to 160 characters, a `units` count of at least 1, and the display
    window bounds `window_start` and `window_end`, where the end must be strictly later
    than the start."
    PRD §3.8: "The loan is created in `status` `REQUESTED` with `returned_condition_grade`,
    `checked_out_at` and `returned_at` null, and its `recovery_until` derived as
    `window_end` plus a 45-day light-recovery buffer — the effective end of this loan's
    occupation of the item, during which the material rests out of the light."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope; `total_count` counts the rows matching the
    filters before pagination is applied."

    Design: Corner/RBAC/rbac_exhibit_loan_creation_shared_by_director_and_archivist
    """
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "original_format": "PHOTO",
             "sensitivity_level": "INTERNAL", "item_label": "PROTO-A"},
            {"unit_count": 2, "original_format": "PHOTO",
             "sensitivity_level": "INTERNAL", "item_label": "PROTO-B"},
        ],
        schedule_overrides={"code": "RB-05", "retention_years": 54,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 7.5",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Product Prototypes",
                          "business_unit": "Engineering",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1980,
                          "latest_record_year": 2005},
        zone_overrides={"zone_code": "Z-RB05", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    item_a_id, item_b_id = holding.item_ids

    loan_a = created(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                item_a_id,
                "2026-08-05T00:00:00Z",
                "2026-08-25T00:00:00Z",
                units=2,
                exhibit_name="Design Gallery",
            ),
            DIRECTOR_A,
        )
    )
    loan_b = created(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                item_b_id,
                "2026-08-05T00:00:00Z",
                "2026-08-25T00:00:00Z",
                units=2,
                exhibit_name="Design Gallery Annex",
            ),
            ARCHIVIST_A,
        )
    )

    assert_fields(loan_a, status="REQUESTED")
    assert_fields(loan_b, status="REQUESTED", archival_item_id=item_b_id)
    assert_nulls(loan_b, "returned_condition_grade", "checked_out_at", "returned_at")
    assert_total_count(client.list_exhibit_loans(PRESERV_A), 2)
    assert_ids_exactly(
        client.list_exhibit_loans(ARCHIVIST_A, {"archival_item_id": item_b_id}),
        [loan_b["id"]],
    )


def test_the_officer_who_screened_a_request_cannot_also_approve_it(client):
    """PRD §2.9: "The comparison is made on `X-User-ID`, and a collision is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.9: "The officer approving or denying an access request must present an
    `X-User-ID` different from the `screened_by` of the request's current screening."
    PRD §3.7: "First, the officer's `X-User-ID` must differ from the `screened_by` of the
    request's current screening, or the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."

    Design: Corner/RBAC/rbac_screener_deciding_own_screening_returns_segregation_of_duties
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 1, "original_format": "PHOTO",
                     "sensitivity_level": "PUBLIC", "item_label": "PLANT-PHOTOS"}],
        schedule_overrides={"code": "RB-06", "retention_years": 55,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 7.6",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Facility Photographs",
                          "business_unit": "Facilities",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 4,
                          "earliest_record_year": 1965,
                          "latest_record_year": 2002},
        zone_overrides={"zone_code": "Z-RB06", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        screening_note="Public imagery.",
        screener=OFFICER_A,
        headers=OFFICER_A,
        requester_overrides={"display_name": "Facilities Planning",
                             "requester_class": "INTERNAL_BUSINESS",
                             "affiliation": "Facilities",
                             "nda_on_file": False},
        purpose="Reference images for a refurbishment study.",
    )
    assert case.screening["screened_by"] == OFFICER_A_ID
    assert case.request["post_screen_risk_score"] == 10

    failed(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_A
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    reloaded = fx.read_request(client, case.request_id)
    assert_fields(reloaded, status="SCREENING", post_screen_risk_score=10)
    assert_nulls(reloaded, "service_fee_cents", "decided_by")


def test_the_counsel_who_cleared_a_deaccession_cannot_approve_it_wearing_the_directors_hat(
    client,
):
    """PRD §2.9: "Three approvals in this system must not be performed by the operator who
    set them up, even though both operators legitimately hold the same role."
    PRD §2.9: "And the director approving a deaccession proposal must present an
    `X-User-ID` different from the proposal's `legal_cleared_by`."
    PRD §3.9: "The approving `X-User-ID` must differ from `legal_cleared_by`, or the
    attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Hop one moves the item `ACCESSIONED → PENDING_DISPOSITION`, with no unit
    movement yet."

    Design: Corner/RBAC/rbac_legal_clearer_approving_deaccession_returns_segregation_of_duties
    """
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 5, "condition_grade": "FAIR",
                     "sensitivity_level": "PUBLIC",
                     "item_label": "BROCHURES-SURPLUS"}],
        schedule_overrides={"code": "RB-07", "retention_years": 56,
                            "disposition_action": "REVIEW",
                            "legal_citation": "Corp Policy 7.7",
                            "min_appraisal_score_for_permanent": 80.00},
        series_overrides={"title": "Surplus Sales Brochures",
                          "business_unit": "Sales",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 10,
                          "earliest_record_year": 1975,
                          "latest_record_year": 1996},
        zone_overrides={"zone_code": "Z-RB07", "temperature_c": 16.0,
                        "relative_humidity_pct": 44.0,
                        "max_overlapping_migration_jobs": 1},
    )
    proposal = fx.make_proposal(
        client,
        holding.item_id,
        stage="DUALLY_CLEARED",
        units=5,
        route="DESTRUCTION",
        rationale="Surplus duplicates with no heritage value.",
        legal_clearer=COUNSEL_A,
        heritage_clearer=DIRECTOR_A,
    )
    assert proposal["legal_cleared_by"] == COUNSEL_A_ID

    failed(
        client.approve_deaccession_proposal(
            proposal["id"], make_headers(COUNSEL_A_ID, ROLE_ARCHIVES_DIRECTOR)
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    refused = fx.read_proposal(client, proposal["id"])
    assert refused["status"] == "DUALLY_CLEARED"
    assert_nulls(refused, "approved_by")
    assert fx.read_item(client, holding.item_id)["status"] == "ACCESSIONED"

    approved = ok(client.approve_deaccession_proposal(proposal["id"], DIRECTOR_B))
    assert_fields(approved, status="APPROVED")
    assert fx.read_item(client, holding.item_id)["status"] == "PENDING_DISPOSITION"
