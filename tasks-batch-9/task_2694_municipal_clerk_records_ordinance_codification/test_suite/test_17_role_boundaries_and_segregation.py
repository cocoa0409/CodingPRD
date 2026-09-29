"""Who may act: the gavel operations that belong to one role alone, three
crossings of the peer-role boundary, the two signatures that refuse the same
pair of hands twice, and the ownership check on an entity-backed identity.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANONYMOUS,
    ANONYMOUS_ALT,
    CITY_CLERK,
    CITY_CLERK_ID,
    CODIFICATION_EDITOR,
    CODIFICATION_EDITOR_FOURTH,
    CODIFICATION_EDITOR_FOURTH_ID,
    CODIFICATION_EDITOR_THIRD,
    CODIFICATION_EDITOR_THIRD_ID,
    DEPUTY_CLERK,
    PRESIDING_OFFICER,
    RECORDS_OFFICER,
    make_requester_headers,
)

EDITORS_ANNEX = {"name": "Editor's Annex", "address": "3 Civic Plaza", "capacity": 20}


def test_the_presiding_officer_opens_reads_and_closes_the_same_sitting():
    """Convening, reading the sitting back and adjourning it are all answered for the
    officer who holds the gavel, and the adjournment leaves exactly one draft
    minutes record behind.

    PRD 2.1: "A `PresidingOfficer` is the mayor or chair. This role calls a meeting
    to order, adjourns it, supplies the tie-breaking vote and exercises the veto, and
    otherwise never touches the record itself."

    Design: Corner/rbac/the_presiding_officer_exercises_the_gavel_operations_no_other_role_holds
    """
    ctx = fx.noticed_meeting(item_types=["REPORT"])
    meeting_id = ctx["meeting"]["id"]

    convened = validate_success(
        api_client.convene_meeting(
            meeting_id, f.convene_payload(6), PRESIDING_OFFICER
        )
    )
    read_back = validate_success(
        api_client.get_meeting(meeting_id, PRESIDING_OFFICER)
    )
    adjourned = validate_success(
        api_client.adjourn_meeting(meeting_id, PRESIDING_OFFICER)
    )

    a.assert_status(convened, "IN_SESSION")
    a.assert_fields(read_back, present_member_count=6, status="IN_SESSION")
    a.assert_status(adjourned, "ADJOURNED")
    minutes, meta = validate_paginated(
        api_client.list_meeting_minutes(meeting_id, PRESIDING_OFFICER)
    )
    a.assert_pagination_meta(meta, total_count=1)
    a.assert_fields(minutes[0], status="DRAFT", revision_number=1)


def test_three_crossings_of_the_peer_role_boundary_are_all_refused_alike():
    """The clerk reaching for the gavel, the deputy reaching for the tally and the
    editor reaching into the meetings surface are one refusal repeated three times,
    and nothing any of them aimed at moves.

    PRD 2.1: "Only once the role is recognised does the service ask whether that role
    is permitted on the endpoint being called; if it is not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/the_clerk_cannot_convene_the_deputy_cannot_tally_and_the_editor_cannot_open_a_venue
    """
    ctx = fx.in_session_meeting(5, ["REPORT"])
    meeting_id = ctx["meeting"]["id"]
    motion = fx.record_motion(meeting_id, headers=DEPUTY_CLERK)

    clerk_at_the_gavel = api_client.adjourn_meeting(meeting_id, CITY_CLERK)
    deputy_at_the_tally = api_client.tally_motion(
        motion["id"], f.tally_payload(3, 2), DEPUTY_CLERK
    )
    editor_at_the_calendar = api_client.create_venue(EDITORS_ANNEX, CODIFICATION_EDITOR)

    validate_error(clerk_at_the_gavel, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    validate_error(deputy_at_the_tally, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    validate_error(editor_at_the_calendar, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
    still_sitting = fx.read_meeting(meeting_id)
    a.assert_status(still_sitting, "IN_SESSION")
    a.assert_nulls(still_sitting, "adjourned_at")
    a.assert_fields(fx.read_motion(motion["id"]), status="SECONDED", outcome="PENDING")


def test_the_officer_who_proposed_the_batch_cannot_be_the_one_who_signs_it():
    """The proposer holds a role the signature endpoint lists and the batch is
    otherwise ready, so the refusal can only be about the identity in the header;
    the same request from a second pair of hands moves forty items' custody.

    PRD 3.9: "Signing the certificate of destruction is available to a `CityClerk` or
    a `RecordsOfficer` and requires a second pair of hands: the acting `X-User-ID`
    must differ from the batch's `proposed_by_officer_id`, or the signature is refused
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." and "On success the batch moves
    `PROPOSED → CERTIFIED`, `certifying_officer_id` records the signer's `X-User-ID`,
    `certified_on` records the supplied date, and the custody counters move:
    `active_item_count` falls by the batch's `item_count` and `destroyed_item_count`
    rises by the same amount."

    Design: Corner/rbac/the_officer_who_proposed_a_destruction_batch_cannot_certify_it
    """
    series = fx.series_eligible_for_destruction(
        40, "2019-06-15", retention_years=5,
        series_code="CC-08", name="Utility billing files",
    )
    batch = fx.proposed_destruction_batch(series["id"], 10, "2019-06-15")

    by_the_proposer = api_client.certify_destruction_batch(
        batch["id"], f.certify_batch_payload("2026-08-01"), RECORDS_OFFICER
    )

    validate_error(by_the_proposer, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    unsigned = fx.read_batch(batch["id"])
    a.assert_status(unsigned, "PROPOSED")
    a.assert_nulls(unsigned, "certified_on", "certifying_officer_id")
    a.assert_custody_triple(
        fx.read_record_series(series["id"]), total=40, active=40, destroyed=0
    )

    signed = validate_success(
        api_client.certify_destruction_batch(
            batch["id"], f.certify_batch_payload("2026-08-01"), CITY_CLERK
        )
    )

    a.assert_fields(
        signed,
        status="CERTIFIED",
        certified_on="2026-08-01",
        certifying_officer_id=CITY_CLERK_ID,
    )
    a.assert_custody_triple(
        fx.read_record_series(series["id"]), total=40, active=30, destroyed=10
    )


def test_the_editor_who_settled_the_conflict_cannot_sign_the_supplement():
    """The bar is stamped on a child row rather than on the cycle: because one
    submission records this editor as its resolver, the certificate is refused for
    them and answered for the editor who filed and locked the cycle.

    PRD 3.7: "and the acting `X-User-ID` must differ from every `resolved_by_user_id`
    recorded on the cycle's submissions, or the attempt is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_editor_who_resolved_the_conflict_cannot_certify_that_supplement_cycle
    """
    ctx = fx.locked_cycle_with_conflict(
        filer=CODIFICATION_EDITOR_FOURTH, supplement_number=9
    )
    cycle_id = ctx["cycle"]["id"]
    winner_id = ctx["submission_one"]["id"]
    loser_id = ctx["submission_two"]["id"]
    resolved = validate_success(
        api_client.resolve_submission_conflict(
            winner_id,
            f.resolve_conflict_payload("MANUAL_OVERRIDE", winner_id),
            CODIFICATION_EDITOR_THIRD,
        )
    )

    by_the_resolver = api_client.certify_supplement_cycle(
        cycle_id, f.certify_cycle_payload("2026-09-30"), CODIFICATION_EDITOR_THIRD
    )

    a.assert_fields(resolved, resolved_by_user_id=CODIFICATION_EDITOR_THIRD_ID)
    a.assert_fields(fx.read_cycle(cycle_id), conflict_count=0)
    validate_error(by_the_resolver, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    uncertified = fx.read_cycle(cycle_id)
    a.assert_status(uncertified, "LOCKED")
    a.assert_nulls(uncertified, "certified_on")

    certified = validate_success(
        api_client.certify_supplement_cycle(
            cycle_id, f.certify_cycle_payload("2026-09-30"), CODIFICATION_EDITOR_FOURTH
        )
    )

    a.assert_fields(certified, status="CERTIFIED", certified_on="2026-09-30")
    a.assert_status(fx.read_submission(winner_id), "ACCEPTED")
    a.assert_status(fx.read_submission(loser_id), "REJECTED")


def test_one_requesters_credential_opens_only_that_requesters_file():
    """The credential is the file's own identifier, so the same header reads one
    request and is turned away from the other twice over — refused as a stranger
    rather than as a reader of something that does not exist.

    PRD 2.1: "On any of those three, a `Requester` whose `X-User-ID` differs from the
    `request_id` in the path is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The
    ownership check runs after the role check and before any existence, shape or state
    checks on the body."

    Design: Corner/rbac/a_requester_cannot_read_or_withdraw_a_different_requesters_request
    """
    mine = fx.create_records_request(ANONYMOUS)
    theirs = fx.create_records_request(
        ANONYMOUS_ALT,
        requester_name="T. Okafor",
        requester_email="t.okafor@example.org",
        subject_description="Planning commission packets 2025",
    )
    my_credential = make_requester_headers(mine["id"])

    own_file = validate_success(
        api_client.get_records_request(mine["id"], my_credential)
    )
    their_file = api_client.get_records_request(theirs["id"], my_credential)
    their_withdrawal = api_client.withdraw_records_request(
        theirs["id"], my_credential
    )
    clerk_read = validate_success(
        api_client.get_records_request(theirs["id"], CITY_CLERK)
    )

    a.assert_fields(own_file, fulfillment_status="RECEIVED", requester_name="M. Rivera")
    read_body = validate_error(
        their_file, ApiErrorId.NOT_RESOURCE_OWNER.value, 403
    )
    assert read_body["error_id"] != ApiErrorId.REQUEST_NOT_FOUND.value
    withdraw_body = validate_error(
        their_withdrawal, ApiErrorId.NOT_RESOURCE_OWNER.value, 403
    )
    assert withdraw_body["error_id"] != ApiErrorId.REQUEST_NOT_FOUND.value
    a.assert_fields(clerk_read, fulfillment_status="RECEIVED")
