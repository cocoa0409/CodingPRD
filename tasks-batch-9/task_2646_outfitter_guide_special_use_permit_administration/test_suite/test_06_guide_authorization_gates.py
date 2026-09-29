"""Linking a guide to a permit: what each end of the reference must prove.

Covers the qualification-state dependency, the two-ended reference validation
with its guide-side screen order, and the nightly sweep's five-link cascade from
one expired wallet card.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_permit,
    assert_compliance_derivation,
    authorize_guide,
    create_approved_operating_plan,
    create_guide,
    create_outfitter,
    create_qualified_guide,
    file_bond,
    file_insurance_certificate,
    guide_authorization_payload,
    list_permit_authorizations,
    qualify_guide,
    read_guide,
    read_permit,
    run_sweep,
    set_clock,
    setup_issued_permit,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]

RITA_LEAD_WFR_7 = {
    "full_name": "Rita Long",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "WFR",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 7,
}
BETA = {
    "legal_name": "Beta River Guides LLC",
    "ein": "410000002",
    "contact_email": "ops@beta.example",
    "prequalification_insurance_verified": True,
}


def test_a_pending_guide_is_refused_although_nothing_else_about_it_is_wrong():
    """PRD §3.6: "The holder authorizes one of its own `QUALIFIED` guides to work under a permit
    by naming the `guide_id`."
    PRD §3.6: "The guide's `status` must be exactly `QUALIFIED`; a `PENDING_QUALIFICATION` or
    `LAPSED` guide is refused with `ERR_GUIDE_NOT_QUALIFIED`."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/cross_entity_state_dependency/guide_authorization_gated_by_guide_qualification_state
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]

    rita = create_guide(outfitter_id, **RITA_LEAD_WFR_7)
    assert rita["status"] == "PENDING_QUALIFICATION"
    assert rita["base_client_capacity"] == 10, (
        "the capacity is already measurable, so no data is missing"
    )
    assert rita["first_aid_cert_type"] == "WFR"
    assert rita["first_aid_expires_on"] == "2030-06-30", (
        "the credential is present, unexpired and outlasts the term"
    )

    before = read_permit(permit_id)
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(rita["id"]), holder
        ),
        ApiErrorId.ERR_GUIDE_NOT_QUALIFIED,
    )

    after = read_permit(permit_id)
    assert after["authorized_client_capacity_total"] == 0
    assert after["version"] == before["version"]
    rows, meta = list_permit_authorizations(permit_id)
    assert rows == [] and meta["total_count"] == 0
    assert read_guide(rita["id"])["status"] == "PENDING_QUALIFICATION"


def test_qualifying_the_guide_is_the_only_change_the_identical_request_needs():
    """PRD §3.1: "Qualification is the program's act, not the holder's: a `PermitSpecialist` or an
    `AuthorizedOfficer` qualifies a guide who is in `PENDING_QUALIFICATION` or `LAPSED`, moving
    it to `QUALIFIED`."
    PRD §3.6: "Its `authorized_client_capacity` is computed once, at this instant, as the lesser
    of the area's `max_clients_per_guide` and the guide's `base_client_capacity`, and is then
    **frozen**"
    PRD §3.6: "The guide's `outfitter_id` must equal the permit's `outfitter_id`, else
    `ERR_GUIDE_OUTFITTER_MISMATCH` — a holder may not borrow another outfitter's guide."

    Design: Difficulty/cross_entity_state_dependency/guide_authorization_gated_by_guide_qualification_state
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]

    rita = create_guide(outfitter_id, **RITA_LEAD_WFR_7)
    payload = guide_authorization_payload(rita["id"])
    validate_error(
        api_client.create_guide_authorization(permit_id, payload, holder),
        ApiErrorId.ERR_GUIDE_NOT_QUALIFIED,
    )

    qualified = qualify_guide(rita["id"])
    assert qualified["status"] == "QUALIFIED"
    assert qualified["qualified_at"].startswith("2027-01-05")

    authorization = validate_success(
        api_client.create_guide_authorization(permit_id, payload, holder), 201
    )
    assert authorization["status"] == "AUTHORIZED"
    assert authorization["authorized_client_capacity"] == 8, "min(8, 10), frozen here"
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8

    beta = create_outfitter(**BETA)
    beta_guide = create_qualified_guide(
        beta["id"], full_name="Cal Vance", seasons_experience=7
    )
    assert beta_guide["status"] == "QUALIFIED"
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(beta_guide["id"]), holder
        ),
        ApiErrorId.ERR_GUIDE_OUTFITTER_MISMATCH,
    )
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8, (
        "a correct status on the wrong parent is still refused"
    )


def test_both_ends_of_the_link_are_checked_and_the_row_reads_from_either_parent():
    """PRD §2.5: "Path parameters are resolved left to right as they appear in the URL, and only
    then are ids carried in the request body resolved, in the order the body fields are listed
    for that endpoint."
    PRD §3.6: "The `qualification_level` must not be `TRAINEE`, else
    `ERR_GUIDE_LEVEL_INELIGIBLE`: a trainee carries a `base_client_capacity` of 0 and can never
    be authorized to lead clients, and this is the only place that error is reachable."
    PRD §3.6: "The credential must also outlast the work: `first_aid_expires_on` must fall on or
    after the permit's `term_end_date`, or else at minimum on or after the `season_close_date` of
    the area for the permit's current season year, and a credential expiring before that season
    close is refused with `ERR_GUIDE_TERM_CONFLICT`."
    PRD §3.6: "Authorizations are listable two ways, both oldest first and both including revoked
    rows unless an optional `status` filter narrows them: by permit, to read the roster, and by
    guide, to read every permit that guide is or was authorized under."

    Design: Corner/endpoints/authorization_link_validates_both_endpoints_of_the_reference_and_is_readable_from_each_side
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]
    assert context["use_area"]["season_close_date"] == "2027-09-30"
    assert context["permit"]["term_end_date"] == "2029-12-31"
    before_version = read_permit(permit_id)["version"]

    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    tom = create_qualified_guide(
        outfitter_id, full_name="Tom Ash", qualification_level="TRAINEE",
        first_aid_cert_type="WFR", first_aid_expires_on="2030-06-30",
        seasons_experience=1,
    )
    pat = create_guide(
        outfitter_id, full_name="Pat Reed", qualification_level="ASSISTANT",
        first_aid_cert_type="WFR", first_aid_expires_on="2030-06-30",
        seasons_experience=4,
    )
    xen = create_qualified_guide(
        outfitter_id, full_name="Xen Ruiz", qualification_level="LEAD",
        first_aid_cert_type="WFR", first_aid_expires_on="2027-06-30",
        seasons_experience=7,
    )
    assert tom["status"] == "QUALIFIED" and pat["status"] == "PENDING_QUALIFICATION"

    validate_error(
        api_client.create_guide_authorization(
            NON_EXISTENT_UUID, guide_authorization_payload(rita["id"]), holder
        ),
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(NON_EXISTENT_UUID), holder
        ),
        ApiErrorId.ERR_GUIDE_NOT_FOUND,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(tom["id"]), holder
        ),
        ApiErrorId.ERR_GUIDE_LEVEL_INELIGIBLE,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(pat["id"]), holder
        ),
        ApiErrorId.ERR_GUIDE_NOT_QUALIFIED,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(xen["id"]), holder
        ),
        ApiErrorId.ERR_GUIDE_TERM_CONFLICT,
    )

    authorization = validate_success(
        api_client.create_guide_authorization(
            permit_id, guide_authorization_payload(rita["id"]), holder
        ),
        201,
    )
    assert authorization["status"] == "AUTHORIZED"
    assert authorization["authorized_at"].startswith("2027-01-05")
    assert authorization["authorized_client_capacity"] == 8

    permit_side, permit_meta = list_permit_authorizations(permit_id)
    assert permit_meta["total_count"] == 1, "five rejected attempts left no partial rows"
    assert permit_side[0]["id"] == authorization["id"]

    guide_side, guide_meta = validate_paginated(
        api_client.list_guide_guide_authorizations(rita["id"], SPECIALIST)
    )
    assert guide_meta["total_count"] == 1
    assert guide_side[0]["id"] == authorization["id"]
    assert guide_side[0]["permit_id"] == permit_id, "one write, visible from both parents"

    permit = read_permit(permit_id)
    assert permit["authorized_client_capacity_total"] == 8
    assert permit["version"] > before_version


BEN_CERT_EXPIRES_MID_OCTOBER = {
    "full_name": "Ben Cruz",
    "qualification_level": "ASSISTANT",
    "first_aid_cert_type": "BASIC_FIRST_AID",
    "first_aid_expires_on": "2027-10-15",
    "seasons_experience": 2,
}


def _active_permit_with_a_lapsing_assistant():
    """An ACTIVE permit whose roster totals exactly the area's party_size_max of
    12, with the clock parked one day after the assistant's certificate expires."""
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    ben = create_qualified_guide(outfitter_id, **BEN_CERT_EXPIRES_MID_OCTOBER)
    rita_auth = authorize_guide(permit_id, rita["id"], outfitter_id)
    ben_auth = authorize_guide(permit_id, ben["id"], outfitter_id)
    assert ben_auth["authorized_client_capacity"] == 4, (
        "a certificate expiring 2027-10-15 clears the 2027-09-30 season close"
    )
    create_approved_operating_plan(permit_id, outfitter_id, 2027)
    file_insurance_certificate(
        permit_id, outfitter_id,
        coverage_amount_cents=context["use_area"]["min_liability_coverage_cents"],
    )
    file_bond(permit_id, outfitter_id, bond_amount_cents=1_000_000)
    permit = activate_permit(permit_id)
    assert permit["administrative_status"] == "ACTIVE"
    assert permit["compliance_status"] == "COMPLIANT"
    assert permit["authorized_client_capacity_total"] == 12
    assert context["use_area"]["party_size_max"] == 12
    set_clock("2027-10-16T00:00:00Z")
    return {
        "permit_id": permit_id,
        "rita": rita,
        "ben": ben,
        "rita_auth": rita_auth,
        "ben_auth": ben_auth,
    }


def test_one_expired_wallet_card_walks_five_links_in_a_single_sweep():
    """PRD §3.9: "**Step two** lapses guides: every `QUALIFIED` guide whose
    `first_aid_expires_on` is strictly before the current logical date moves to `LAPSED` and its
    `base_client_capacity` recomputes to 0."
    PRD §3.9: "When a guide lapses in step two, its authorizations are revoked with reason
    `GUIDE_LAPSED`, each affected permit's `authorized_client_capacity_total` is recomputed, and
    any permit whose recomputed total falls below its area's `party_size_max` while
    `administrative_status` is `ACTIVE` has its `compliance_status` re-derived to `PROBATION`."
    PRD §3.9: "and step five must follow step four, or a permit suspended by step four would be
    left with an authorized guide roster."
    PRD §3.9: "`certificates_expired`, `bonds_expired`, `guides_lapsed`, `permits_expired`,
    `authorizations_revoked` and `permits_suspended` count the rows each step moved."

    Design: Difficulty/transitive_cascade/sweep_guide_lapse_authorization_ratio_cascade
    """
    stage = _active_permit_with_a_lapsing_assistant()

    report = run_sweep()
    assert report["guides_lapsed"] == 1
    assert report["authorizations_revoked"] == 1
    assert report["permits_suspended"] == 0
    assert report["certificates_expired"] == 0
    assert report["bonds_expired"] == 0
    assert report["permits_expired"] == 0
    assert report["swept_at"].startswith("2027-10-16")

    lapsed = read_guide(stage["ben"]["id"])
    assert lapsed["status"] == "LAPSED", "hop one: 2027-10-15 is before the logical date"
    assert lapsed["base_client_capacity"] == 0, "hop two"
    assert read_guide(stage["rita"]["id"])["status"] == "QUALIFIED", (
        "2030-06-30 is not before 2027-10-16"
    )

    rows, _meta = list_permit_authorizations(stage["permit_id"])
    by_id = {row["id"]: row for row in rows}
    revoked = by_id[stage["ben_auth"]["id"]]
    assert revoked["status"] == "REVOKED", "hop three"
    assert revoked["revocation_reason_code"] == "GUIDE_LAPSED"
    assert revoked["authorized_client_capacity"] == 4, "the frozen figure is kept on record"
    assert by_id[stage["rita_auth"]["id"]]["status"] == "AUTHORIZED"

    permit = read_permit(stage["permit_id"])
    assert permit["authorized_client_capacity_total"] == 8, (
        "hop four: the surviving row's frozen 8 alone"
    )
    assert permit["compliance_status"] == "PROBATION", "hop five: 8 is below party_size_max 12"
    assert permit["administrative_status"] == "ACTIVE", (
        "a ratio shortfall is a good-standing problem, not a suspension"
    )
    assert permit["suspension_count"] == 0


def test_a_second_immediate_sweep_moves_nothing_and_holds_the_derived_pair():
    """PRD §3.9: "**Step two** lapses guides: every `QUALIFIED` guide whose
    `first_aid_expires_on` is strictly before the current logical date moves to `LAPSED` and its
    `base_client_capacity` recomputes to 0."
    PRD §3.9: "**Step five** revokes authorizations whose basis is gone: every `AUTHORIZED`
    authorization whose guide has lapsed or whose permit has left the operable set moves to
    `REVOKED`, with reason `GUIDE_LAPSED` for a lapsed guide, `PERMIT_SUSPENDED` for a permit
    suspended during this run, and `PERMIT_CLOSED` for a permit that expired, was revoked or was
    closed."
    PRD §3.9: "Every row the batch mutates has its `version` advanced, exactly as though a
    request had written it directly."

    Design: Difficulty/transitive_cascade/sweep_guide_lapse_authorization_ratio_cascade
    """
    stage = _active_permit_with_a_lapsing_assistant()
    run_sweep()
    after_first = read_permit(stage["permit_id"])
    ben_after_first = read_guide(stage["ben"]["id"])
    assert after_first["compliance_status"] == "PROBATION"

    second = run_sweep()
    assert second["guides_lapsed"] == 0, "a LAPSED guide is no longer in the QUALIFIED set"
    assert second["authorizations_revoked"] == 0, "REVOKED is terminal"
    assert second["permits_suspended"] == 0
    assert second["certificates_expired"] == 0
    assert second["bonds_expired"] == 0
    assert second["permits_expired"] == 0

    permit = read_permit(stage["permit_id"])
    assert permit["administrative_status"] == "ACTIVE"
    # PRD §3.8 gives the compliance dimension exactly three terms — points,
    # `insurance_current` and `fee_delinquent` — and the idle pass re-derives on
    # each of them; the ratio shortfall is not one of them, so only the
    # derivation rule itself is asserted here.
    assert_compliance_derivation(permit)
    assert permit["authorized_client_capacity_total"] == 8
    assert read_guide(stage["ben"]["id"])["version"] == ben_after_first["version"], (
        "the idle pass writes nothing, so no version advances"
    )
    rows, meta = list_permit_authorizations(stage["permit_id"])
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["AUTHORIZED", "REVOKED"]
