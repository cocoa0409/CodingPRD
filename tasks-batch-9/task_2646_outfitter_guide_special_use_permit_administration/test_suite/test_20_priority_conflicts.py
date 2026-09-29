"""One request, two broken rules, and which one the caller is told about.

Covers the pinned tier collisions: a suspended permit beating the service-day
overage, an expired first-aid certificate beating the full roster, and existence
beating ownership.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    accept_use_report,
    authorize_guide,
    bond_payload,
    create_outfitter,
    create_published_assessment,
    create_qualified_guide,
    create_screened_application,
    create_use_area,
    issue_permit,
    list_bonds,
    list_permit_authorizations,
    list_use_reports,
    read_guide,
    read_permit,
    read_use_report,
    revoke_authorization,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    trip_use_report_payload,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

OFFICER = TEST_USERS["authorized_officer_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
LONG_TERM = {"term_start_date": "2027-01-01", "term_end_date": "2029-12-31"}
OFFICER_ORDER = {
    "suspension_reason_code": "OFFICER_ORDER",
    "suspended_until_date": "2027-12-01",
}
BETA = {
    "legal_name": "Beta Trails Co",
    "ein": "410000002",
    "contact_email": "ops@beta.example",
    "prequalification_insurance_verified": True,
}


def _suspended_permit():
    """An ACTIVE 200-day permit suspended by officer order, read at a clock late
    enough that a mid-season reporting period has elapsed."""
    context = setup_active_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    suspended = validate_success(
        api_client.suspend_permit(context["permit"]["id"], dict(OFFICER_ORDER), OFFICER)
    )
    assert suspended["administrative_status"] == "SUSPENDED"
    assert suspended["authorized_client_capacity_total"] == 0
    set_clock("2027-09-01T00:00:00Z")
    return context


def test_the_suspended_permit_is_reported_before_the_service_day_overage():
    """PRD §2.5: "A use report filed against a suspended permit that would *also* breach the
    permit's service-day cap returns the state error `ERR_PERMIT_NOT_OPERATIONAL`, never the fiscal
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."
    PRD §2.5: "Checks are evaluated strictly in the following order, and the **first** violated
    check produces the response; no later check is consulted."
    PRD §3.7: "The report must be `SUBMITTED`, else `ERR_USE_REPORT_STATE_INVALID`; and the
    cumulative `service_days_used` over the permit's accepted reports for the season, *including
    this one*, must not exceed the permit's `authorized_service_days`, else
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Difficulty/priority_pair_validation_conflict/suspended_permit_beats_service_day_overage
    """
    context = _suspended_permit()
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]
    lead = context["guides"][0]
    overage = trip_use_report_payload(
        period_start_date="2027-05-15", period_end_date="2027-06-14",
        service_days_used=250, client_count=8, gross_revenue_cents=2_000_000,
    )

    validate_error(
        api_client.create_trip_use_report(permit_id, dict(overage), holder),
        ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
        409,
    )
    _rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 0, "the refused filing wrote no report row"

    reinstated = validate_success(api_client.reinstate_permit(permit_id, OFFICER))
    assert reinstated["administrative_status"] == "ACTIVE"
    assert reinstated["authorized_client_capacity_total"] == 0
    authorize_guide(permit_id, lead["id"], context["outfitter"]["id"])
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8

    filed = validate_success(
        api_client.create_trip_use_report(permit_id, dict(overage), holder), 201
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["service_days_used"] == 250

    validate_error(
        api_client.accept_trip_use_report(filed["id"], SPECIALIST),
        ApiErrorId.ERR_SERVICE_DAY_LIMIT_EXCEEDED,
        422,
    )
    assert read_use_report(filed["id"])["status"] == "SUBMITTED", (
        "the fiscal rule was deferred behind the state defect, never skipped"
    )
    assert read_permit(permit_id)["service_days_used_ytd"] == 0

    at_the_cap = validate_success(
        api_client.create_trip_use_report(
            permit_id,
            trip_use_report_payload(
                period_start_date="2027-06-15", period_end_date="2027-07-15",
                service_days_used=200, client_count=8, gross_revenue_cents=2_000_000,
            ),
            holder,
        ),
        201,
    )
    accepted = accept_use_report(at_the_cap["id"])
    assert accepted["status"] == "ACCEPTED"
    assert read_permit(permit_id)["service_days_used_ytd"] == 200, (
        "200 days is exactly the inclusive cap, so it is admissible while 250 is not"
    )


def test_the_state_error_masks_both_the_ratio_and_the_deduction_cap_until_the_permit_is_operational():
    """PRD §2.5: "A use report filed against a suspended permit that would *also* breach the
    permit's service-day cap returns the state error `ERR_PERMIT_NOT_OPERATIONAL`, never the fiscal
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."
    PRD §3.7: "`client_count` must not exceed the permit's `authorized_client_capacity_total` — the
    client-to-guide ratio must not merely have been satisfiable, it must have been satisfied by the
    trips actually run — else `ERR_CLIENT_GUIDE_RATIO_UNMET`."
    PRD §3.7: "And deductions are capped: `allowable_deductions_cents` must not exceed 15 percent of
    `gross_revenue_cents`, computed as the floor of that product, else `ERR_DEDUCTIONS_EXCEED_CAP`."
    PRD §3.7: "the cumulative `service_days_used` over the permit's accepted reports for the season,
    *including this one*, must not exceed the permit's `authorized_service_days`, else
    `ERR_SERVICE_DAY_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_permit_beats_service_day_overage
    """
    context = _suspended_permit()
    permit_id = context["permit"]["id"]
    holder = context["holder_headers"]
    lead = context["guides"][0]
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0, (
        "the suspension collapsed the capacity, so the ratio rule is broken too"
    )

    clean = trip_use_report_payload(
        period_start_date="2027-06-15", period_end_date="2027-07-15",
        service_days_used=100, client_count=8, gross_revenue_cents=2_000_000,
        allowable_deductions_cents=0,
    )
    greedy = trip_use_report_payload(
        period_start_date="2027-05-15", period_end_date="2027-06-14",
        service_days_used=250, client_count=8, gross_revenue_cents=2_000_000,
        allowable_deductions_cents=300_001,
    )

    for body in (clean, greedy):
        validate_error(
            api_client.create_trip_use_report(permit_id, dict(body), holder),
            ApiErrorId.ERR_PERMIT_NOT_OPERATIONAL,
            409,
        )
    _rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 0

    validate_success(api_client.reinstate_permit(permit_id, OFFICER))
    authorize_guide(permit_id, lead["id"], context["outfitter"]["id"])
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8

    validate_error(
        api_client.create_trip_use_report(permit_id, dict(greedy), holder),
        ApiErrorId.ERR_DEDUCTIONS_EXCEED_CAP,
        422,
    )

    at_the_deduction_cap = dict(greedy, allowable_deductions_cents=300_000)
    filed = validate_success(
        api_client.create_trip_use_report(permit_id, at_the_deduction_cap, holder), 201
    )
    assert filed["allowable_deductions_cents"] == 300_000, "exactly 15 percent is admissible"
    assert filed["adjusted_gross_revenue_cents"] == 1_700_000
    validate_error(
        api_client.accept_trip_use_report(filed["id"], SPECIALIST),
        ApiErrorId.ERR_SERVICE_DAY_LIMIT_EXCEEDED,
        422,
    )
    assert read_use_report(filed["id"])["status"] == "SUBMITTED"
    assert read_permit(permit_id)["service_days_used_ytd"] == 0

    accepted = accept_use_report(
        validate_success(
            api_client.create_trip_use_report(permit_id, dict(clean), holder), 201
        )["id"]
    )
    assert accepted["status"] == "ACCEPTED"
    assert read_permit(permit_id)["service_days_used_ytd"] == 100
    rows, meta = list_use_reports(params={"permit_id": permit_id})
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["SUBMITTED", "ACCEPTED"], (
        "listings run by period_start_date ascending, and the overlong report never accepted"
    )


def _roster_of(count, permit_id, outfitter_id):
    """Qualify and authorize `count` LEAD/WFR guides whose credentials outlast the
    permit's term, each freezing the area's per-guide maximum of eight clients."""
    guides, authorizations = [], []
    for index in range(count):
        guide = create_qualified_guide(outfitter_id, full_name=f"Lead Guide {index + 1}")
        guides.append(guide)
        assert guide["base_client_capacity"] == 10
        authorizations.append(authorize_guide(permit_id, guide["id"], outfitter_id))
    assert all(row["authorized_client_capacity"] == 8 for row in authorizations)
    return guides, authorizations


def test_the_expired_first_aid_certificate_is_reported_before_the_full_roster():
    """PRD §2.5: "A guide offered to a permit whose roster is already full, whose first aid
    certificate has also expired, returns the safety error `ERR_FIRST_AID_CERT_EXPIRED` rather than
    the structural `ERR_GUIDE_ROSTER_FULL` — safety outranks the roster cap."
    PRD §3.6: "Finally the roster is capped: at most **8** authorizations with `status` `AUTHORIZED`
    may stand on one permit at a time, and the ninth is `ERR_GUIDE_ROSTER_FULL`."
    PRD §3.6: "unexpired as of the authorization date, with `first_aid_expires_on` on or after the
    current logical date, else `ERR_FIRST_AID_CERT_EXPIRED`"
    PRD §2.5: "The certificate itself is judged before the guide's derived qualification status, so a
    guide who has lapsed *because* the certificate expired returns `ERR_FIRST_AID_CERT_EXPIRED`;
    `ERR_GUIDE_NOT_QUALIFIED` is reachable only for a guide still awaiting its first qualification."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Difficulty/priority_pair_validation_conflict/expired_first_aid_beats_full_guide_roster
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    _guides, _authorizations = _roster_of(8, permit_id, outfitter_id)

    expiring = create_qualified_guide(
        outfitter_id, full_name="Nora Short", first_aid_expires_on="2027-10-15"
    )
    spare = create_qualified_guide(outfitter_id, full_name="Owen Spare")
    full = read_permit(permit_id)
    assert full["authorized_client_capacity_total"] == 64
    version_before = full["version"]

    set_clock("2027-10-16T00:00:00Z")
    assert read_guide(expiring["id"])["status"] == "QUALIFIED", (
        "no sweep has run, so the guide has not lapsed yet and the certificate date is what bites"
    )

    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": expiring["id"]},
            make_outfitter_representative_headers(outfitter_id),
        ),
        ApiErrorId.ERR_FIRST_AID_CERT_EXPIRED,
        422,
    )

    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": spare["id"]},
            make_outfitter_representative_headers(outfitter_id),
        ),
        ApiErrorId.ERR_GUIDE_ROSTER_FULL,
        409,
    )

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 8, "neither refusal wrote a row"
    assert {row["status"] for row in rows} == {"AUTHORIZED"}
    unchanged = read_permit(permit_id)
    assert unchanged["authorized_client_capacity_total"] == 64
    assert unchanged["version"] == version_before


def test_each_of_the_two_colliding_rules_is_reachable_alone_before_they_collide():
    """PRD §2.5: "A guide offered to a permit whose roster is already full, whose first aid
    certificate has also expired, returns the safety error `ERR_FIRST_AID_CERT_EXPIRED` rather than
    the structural `ERR_GUIDE_ROSTER_FULL` — safety outranks the roster cap."
    PRD §3.6: "Finally the roster is capped: at most **8** authorizations with `status` `AUTHORIZED`
    may stand on one permit at a time, and the ninth is `ERR_GUIDE_ROSTER_FULL`."
    PRD §3.6: "The revoked row keeps its frozen `authorized_client_capacity` for the audit record but
    stops counting toward the permit's total, which is again recomputed as a fresh sum"
    PRD §3.6: "The permit's `authorized_client_capacity_total` is then recomputed as a fresh sum of
    `authorized_client_capacity` over the permit's `AUTHORIZED` rows — always a full re-summation,
    never an increment — and the permit's `version` advances."

    Design: Difficulty/priority_pair_validation_conflict/expired_first_aid_beats_full_guide_roster
    """
    context = setup_issued_permit(
        application_overrides={"requested_service_days": 200},
        permit_overrides=dict(LONG_TERM),
    )
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    holder = make_outfitter_representative_headers(outfitter_id)
    _seven, authorizations = _roster_of(7, permit_id, outfitter_id)

    expiring = create_qualified_guide(
        outfitter_id, full_name="Nora Short", first_aid_expires_on="2027-10-15"
    )
    eighth = create_qualified_guide(outfitter_id, full_name="Lead Guide 8")
    ninth = create_qualified_guide(outfitter_id, full_name="Lead Guide 9")
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 56

    set_clock("2027-10-16T00:00:00Z")

    validate_error(
        api_client.create_guide_authorization(permit_id, {"guide_id": expiring["id"]}, holder),
        ApiErrorId.ERR_FIRST_AID_CERT_EXPIRED,
        422,
    )

    eighth_row = validate_success(
        api_client.create_guide_authorization(permit_id, {"guide_id": eighth["id"]}, holder), 201
    )
    assert eighth_row["status"] == "AUTHORIZED"
    assert eighth_row["authorized_client_capacity"] == 8
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 64

    validate_error(
        api_client.create_guide_authorization(permit_id, {"guide_id": ninth["id"]}, holder),
        ApiErrorId.ERR_GUIDE_ROSTER_FULL,
        409,
    )
    validate_error(
        api_client.create_guide_authorization(permit_id, {"guide_id": expiring["id"]}, holder),
        ApiErrorId.ERR_FIRST_AID_CERT_EXPIRED,
        422,
    )

    revoked = revoke_authorization(authorizations[0]["id"], outfitter_id)
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_reason_code"] == "HOLDER_REQUEST"
    assert revoked["authorized_client_capacity"] == 8, "the frozen figure survives on the row"
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 56

    ninth_row = validate_success(
        api_client.create_guide_authorization(permit_id, {"guide_id": ninth["id"]}, holder), 201
    )
    assert ninth_row["authorized_client_capacity"] == 8
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 64, (
        "a revoked row frees exactly one slot, because the cap counts AUTHORIZED rows only"
    )

    validate_error(
        api_client.create_guide_authorization(permit_id, {"guide_id": expiring["id"]}, holder),
        ApiErrorId.ERR_FIRST_AID_CERT_EXPIRED,
    )

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 9, "eight original rows plus the replacement; refusals wrote none"
    assert [row["status"] for row in rows] == ["REVOKED"] + ["AUTHORIZED"] * 8


def _rival_holders():
    """Beta holding a 100-day ISSUED permit on Bear River West, and Alpine
    registered on the same area with no permit of its own."""
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"], determined_capacity_service_days=900)
    beta = create_outfitter(**BETA)
    alpine = create_outfitter()
    application = create_screened_application(
        beta["id"], area["id"], requested_service_days=100
    )
    permit = issue_permit(
        application["id"], term_start_date="2027-01-01", term_end_date="2029-12-31"
    )
    assert permit["outfitter_id"] == beta["id"]
    assert permit["administrative_status"] == "ISSUED"
    return {"area": area, "beta": beta, "alpine": alpine, "permit": permit}


def test_the_missing_permit_in_the_path_is_reported_before_the_ownership_violation():
    """PRD §2.5: "**Existence** — every referenced record resolves. Path parameters are resolved
    left to right as they appear in the URL, and only then are ids carried in the request body
    resolved, in the order the body fields are listed for that endpoint."
    PRD §2.5: "**Ownership** — an `OutfitterRepresentative` is writing only against its own
    outfitter's resources (`ERR_NOT_RESOURCE_OWNER`, 403)."
    PRD §2.5: "Checks are evaluated strictly in the following order, and the **first** violated
    check produces the response; no later check is consulted."
    PRD §3.6: "All three are holder-only acts, and a representative acting on a permit that is not
    their own outfitter's is refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.6: "while `bond_current` is always evaluated against the permit's *current* requirement,
    and is true exactly when some `ACTIVE` bond on the permit carries a `bond_amount_cents` at or
    above it."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no `updated_at`
    refresh and no `version` increment"

    Design: Difficulty/priority_pair_validation_conflict/missing_permit_beats_ownership_violation
    """
    stage = _rival_holders()
    permit_id = stage["permit"]["id"]
    alpine_headers = make_outfitter_representative_headers(stage["alpine"]["id"])
    beta_headers = make_outfitter_representative_headers(stage["beta"]["id"])
    body = bond_payload()

    validate_error(
        api_client.create_bond(NON_EXISTENT_UUID, dict(body), alpine_headers),
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_bond(permit_id, dict(body), alpine_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    _rows, meta = list_bonds(permit_id)
    assert meta["total_count"] == 0, "neither refusal filed a bond"
    assert read_permit(permit_id)["bond_current"] is False
    version_before = read_permit(permit_id)["version"]

    filed = validate_success(api_client.create_bond(permit_id, dict(body), beta_headers), 201)
    assert filed["permit_id"] == permit_id
    assert filed["bond_amount_cents"] == 1_000_000
    rows, meta = list_bonds(permit_id)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == filed["id"]
    after = read_permit(permit_id)
    assert after["bond_current"] is True
    assert after["version"] > version_before, "only the accepted filing moved the permit"


def test_the_body_id_is_resolved_before_ownership_and_before_the_employer_check():
    """PRD §2.5: "**Existence** — every referenced record resolves. Path parameters are resolved
    left to right as they appear in the URL, and only then are ids carried in the request body
    resolved, in the order the body fields are listed for that endpoint."
    PRD §2.5: "**Ownership** — an `OutfitterRepresentative` is writing only against its own
    outfitter's resources (`ERR_NOT_RESOURCE_OWNER`, 403)."
    PRD §3.6: "The guide's `outfitter_id` must equal the permit's `outfitter_id`, else
    `ERR_GUIDE_OUTFITTER_MISMATCH` — a holder may not borrow another outfitter's guide."
    PRD §3.6: "The authorization is created `AUTHORIZED` with `authorized_at` stamped from the
    logical clock and `revoked_at`, `revocation_reason_code` null."

    Design: Difficulty/priority_pair_validation_conflict/missing_permit_beats_ownership_violation
    """
    stage = _rival_holders()
    permit_id = stage["permit"]["id"]
    alpine_headers = make_outfitter_representative_headers(stage["alpine"]["id"])
    beta_headers = make_outfitter_representative_headers(stage["beta"]["id"])
    alpine_guide = create_qualified_guide(stage["alpine"]["id"], full_name="Alma Drift")
    beta_guide = create_qualified_guide(stage["beta"]["id"], full_name="Bram Ford")

    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": NON_EXISTENT_UUID}, alpine_headers
        ),
        ApiErrorId.ERR_GUIDE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_guide_authorization(
            NON_EXISTENT_UUID, {"guide_id": NON_EXISTENT_UUID}, alpine_headers
        ),
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": alpine_guide["id"]}, alpine_headers
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": alpine_guide["id"]}, beta_headers
        ),
        ApiErrorId.ERR_GUIDE_OUTFITTER_MISMATCH,
        422,
    )

    _rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 0
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0

    row = validate_success(
        api_client.create_guide_authorization(
            permit_id, {"guide_id": beta_guide["id"]}, beta_headers
        ),
        201,
    )
    assert row["status"] == "AUTHORIZED"
    assert row["guide_id"] == beta_guide["id"]
    assert row["revoked_at"] is None
    assert row["revocation_reason_code"] is None
    assert row["authorized_at"].startswith("2027-01-05")
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8
