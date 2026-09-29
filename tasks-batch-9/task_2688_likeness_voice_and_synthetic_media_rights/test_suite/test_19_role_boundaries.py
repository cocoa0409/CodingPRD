"""Who may act: exclusive offices, shared reads, ownership bindings, second hands."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assertions,
    build_user_headers,
    factories,
    fixtures,
    make_rights_administrator_headers,
    validate_error,
    validate_success,
)

ADVERTISING_GRANT = {"permitted_use_notes": "Ads"}

CHEAPER_UNION_ROW = {"minimum_initial_cents": 100_000, "minimum_per_use_cents": 50_000}

VOICE_SAMPLE = {
    "asset_kind": "VOICE_SAMPLE",
    "capture_ref": "cap-001",
    "payload_digest": "sha256:aaa",
}

VOICE_BUILD = {"replica_kind": "VOICE", "build_ref": "build-001"}

US_SPOT = {
    "licensee_name": "Northlight",
    "intended_use_description": "US spot",
    "projected_impressions": 500_000,
}

FAINT_DETECTION = {
    "suspect_url": "https://pirate.example/x",
    "detected_view_count": 1_000,
    "match_confidence": 0.400,
}


def _a_built_replica_over_an_active_grant():
    """One talent, an active grant, one stored sample and a built replica."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.register_biometric_asset(scenario, VOICE_SAMPLE)
    fixtures.build_replica(scenario, VOICE_BUILD)
    return scenario


def _approve_the_replica(scenario, headers):
    """Send the talent-side approval under whichever headers are supplied."""
    return api_client.approve_replica_for_use(
        scenario["replica"]["id"], factories.approve_replica_payload(), headers
    )


def _submit_the_spot(scenario, headers):
    """Send one identical performance submission under the supplied headers."""
    return api_client.create_generated_performance(
        factories.generated_performance_payload(scenario["replica"]["id"], **US_SPOT),
        headers,
    )


def _open_a_case(scenario, headers):
    """Send one identical detection under the supplied headers."""
    return api_client.create_infringement_case(
        factories.infringement_case_payload(scenario["talent"]["id"], **FAINT_DETECTION),
        headers,
    )


def _dismiss(scenario, headers):
    """Send the same dismissal under the supplied headers."""
    return api_client.triage_infringement_case(
        scenario["case"]["id"], factories.triage_payload("DISMISS"), headers
    )


def _escalate(scenario, headers):
    """Send the same escalation under the supplied headers."""
    return api_client.escalate_infringement_case(
        scenario["case"]["id"], factories.escalate_payload(), headers
    )


def test_every_office_may_exercise_the_operation_that_belongs_to_it():
    """Reference data, replica approval, submission and detection each land.

    The clearance office's remit is stated plainly: "It owns reference data,
    talent records, consent drafting, custody of captured samples, replica
    building and legal escalation." The clearing decision is not its to make:
    "Approval for use is the talent's decision, exercised by a
    `TalentRepresentative` whose identifier equals the replica's `talent_id`, or
    by an `EstateRepresentative` whose identifier is the `VERIFIED` estate
    authority of that talent; the request may carry an optional
    `approval_note`." The output is the producer's own: "The server records it as
    `licensee_user_id` on the generated performance that the producer created and
    copies that value onto every license issued from it; ownership checks compare
    `X-User-ID` to that recorded `licensee_user_id` rather than to any entity's
    `id`, and a mismatch is `ERR_NOT_LICENSEE_OWNER` (HTTP 403)." And monitoring
    belongs to the fourth office: "A `ComplianceOfficer` opens a case when
    monitoring turns up synthetic content that may not be licensed."

    Design: Corner/rbac/each_offices_exclusive_operations_are_closed_to_the_other_roles
    """
    scenario = _a_built_replica_over_an_active_grant()

    row = validate_success(
        api_client.create_union_minimum_schedule(
            factories.union_minimum_payload(**CHEAPER_UNION_ROW),
            scenario["admin_headers"],
        ),
        201,
    )
    assert row["minimum_per_use_cents"] == 50_000

    replica = validate_success(
        _approve_the_replica(scenario, scenario["talent_rep_headers"]), 200
    )
    assert replica["status"] == "APPROVED_FOR_USE"
    assert replica["approved_by_user_id"] == scenario["talent"]["id"]

    performance = validate_success(
        _submit_the_spot(scenario, scenario["licensee_headers"]), 201
    )
    assert performance["review_status"] == "SUBMITTED"
    assert performance["licensee_user_id"] == scenario["licensee_user_id"]

    case = validate_success(_open_a_case(scenario, scenario["compliance_headers"]), 201)
    assert case["status"] == "DETECTED"
    assert case["triaged_by_user_id"] is None


def test_the_same_four_operations_are_closed_to_every_foreign_role():
    """A licensee cannot self-clear, an administrator cannot submit or triage.

    The PRD states: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." That rung is answered before any other:
    "Authentication comes first: the header check that yields
    `ERR_UNAUTHENTICATED`, then the role-authorization check that yields
    `ERR_ROLE_NOT_PERMITTED`." The talent record is the clearance office's to
    open: "A `RightsAdministrator` creates one by supplying the performer's
    `legal_name` (1 to 200 characters, not blank), the `domicile_state_code` of
    legal domicile (exactly two uppercase letters), and optionally a
    `union_code`, which is `NONE`, `SAG_AFTRA` or `AFM` and defaults to `NONE`."
    The fork on a detection is the officer's: "Triage is the
    `ComplianceOfficer`'s fork and takes a `decision` of `DISMISS` or
    `ISSUE_TAKEDOWN`." The last refusal shows the role rung outranking the state
    rung, since a dismissed case could never be escalated in any event: "The case
    must be `TAKEDOWN_ISSUED`, or escalation draws `ERR_INVALID_CASE_STATE`."

    Design: Corner/rbac/each_offices_exclusive_operations_are_closed_to_the_other_roles
    """
    scenario = _a_built_replica_over_an_active_grant()

    intruding_create = api_client.create_talent(
        factories.talent_payload(), scenario["licensee_headers"]
    )
    validate_error(intruding_create, "ERR_ROLE_NOT_PERMITTED")
    assert intruding_create.status_code == 403

    self_clearance = _approve_the_replica(scenario, scenario["licensee_headers"])
    validate_error(self_clearance, "ERR_ROLE_NOT_PERMITTED")
    assert self_clearance.status_code == 403
    assert fixtures.refresh_replica(scenario)["status"] == "BUILT"

    office_submission = _submit_the_spot(scenario, scenario["admin_headers"])
    validate_error(office_submission, "ERR_ROLE_NOT_PERMITTED")
    assert office_submission.status_code == 403

    fixtures.open_case(scenario, FAINT_DETECTION)
    office_triage = _dismiss(scenario, scenario["admin_headers"])
    validate_error(office_triage, "ERR_ROLE_NOT_PERMITTED")
    assert office_triage.status_code == 403

    dismissed = validate_success(_dismiss(scenario, scenario["compliance_headers"]), 200)
    assert dismissed["status"] == "DISMISSED_NO_ACTION"
    assert dismissed["triaged_by_user_id"] == scenario["compliance_user_id"]

    officer_escalation = _escalate(scenario, scenario["second_compliance_headers"])
    validate_error(officer_escalation, "ERR_ROLE_NOT_PERMITTED")
    assert officer_escalation.status_code == 403


def test_the_role_bar_answers_before_the_asset_needs_to_exist_at_all():
    """An unknown sample is a 403 to the wrong office and a 404 to the right one.

    The PRD fixes the ordering: "These two checks precede every other check in
    the system." Custody of the material is the clearance office's own: "It owns
    reference data, talent records, consent drafting, custody of captured
    samples, replica building and legal escalation." Only once the caller is
    entitled to act does the identifier itself get looked up, and the rungs that
    do that lookup carry their own status: "Each of these rungs governs wherever
    an identifier of that type is accepted, and all of them carry HTTP 404."

    Design: Corner/rbac/each_offices_exclusive_operations_are_closed_to_the_other_roles
    """
    scenario = _a_built_replica_over_an_active_grant()

    wrong_office = api_client.purge_biometric_asset(
        NON_EXISTENT_UUID, factories.purge_payload(), scenario["compliance_headers"]
    )
    validate_error(wrong_office, "ERR_ROLE_NOT_PERMITTED")
    assert wrong_office.status_code == 403

    right_office = api_client.purge_biometric_asset(
        NON_EXISTENT_UUID, factories.purge_payload(), scenario["admin_headers"]
    )
    validate_error(right_office, "ERR_BIOMETRIC_ASSET_NOT_FOUND")
    assert right_office.status_code == 404


SECOND_DETECTION = {
    "suspect_url": "https://pirate.example/y",
    "detected_view_count": 1_000,
    "match_confidence": 0.400,
}


def _a_takedown_beside_an_active_grant():
    """One active grant to read, and one case already at TAKEDOWN_ISSUED."""
    scenario = fixtures.register_state_law_profile()
    fixtures.create_talent(scenario)
    fixtures.draft_consent_grant(scenario, ADVERTISING_GRANT)
    fixtures.countersign_grant(scenario)
    fixtures.open_case(scenario, SECOND_DETECTION)
    fixtures.triage_case(scenario, "ISSUE_TAKEDOWN")
    return scenario


def _read_the_grant(scenario, headers):
    """Read the scenario's grant under whichever headers are supplied."""
    return validate_success(
        api_client.get_consent_grant(scenario["grant"]["id"], headers), 200
    )


def test_a_shared_read_returns_one_identical_row_to_every_role_that_may_see_it():
    """Four offices read the same grant and receive the same payload.

    The PRD names the whole cast: "The five roles are `RightsAdministrator`,
    `TalentRepresentative`, `EstateRepresentative`, `LicenseeProducer` and
    `ComplianceOfficer`." A read is answered with the row itself, and nothing in
    the answer turns on who asked: "Every other successful operation — reads,
    lists, state transitions, attestations, the sweep and the clock — returns HTTP
    200 with the affected resource, the requested resource, or the operation's
    report in `data`." Only an unauthorized role is turned away: "If the headers
    are well formed but the named role is not authorized for the endpoint being
    called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/shared_reads_and_the_shared_closure_action_admit_every_declared_role
    """
    scenario = _a_takedown_beside_an_active_grant()

    readings = [
        _read_the_grant(scenario, scenario["admin_headers"]),
        _read_the_grant(scenario, scenario["compliance_headers"]),
        _read_the_grant(scenario, scenario["talent_rep_headers"]),
        _read_the_grant(scenario, scenario["licensee_headers"]),
    ]

    assert readings[0]["status"] == "ACTIVE"
    assert readings[0]["id"] == scenario["grant"]["id"]
    for reading in readings[1:]:
        assert reading == readings[0]


def test_the_officer_who_triaged_the_case_may_also_be_the_one_who_closes_it():
    """Closure is shared, and only escalation carries the second-hands bar.

    The PRD states: "Closure takes an `outcome` and may be performed by either a
    `RightsAdministrator` or a `ComplianceOfficer`." The branch decides the
    resting state: "From `TAKEDOWN_ISSUED`, an `outcome` of `REMOVED` moves the
    case `TAKEDOWN_ISSUED → RESOLVED_REMOVED` with `closure_outcome` recorded as
    `VOLUNTARY_REMOVAL`; no holds were ever applied on that branch, so nothing is
    released." The duty bar is confined to two operations, neither of them
    closure: "Two duties in this office are deliberately segregated, and both are
    enforced by comparing recorded operator identifiers. The `RightsAdministrator`
    who verifies an estate authority must not be the same user recorded as that
    authority's `submitted_by_user_id`, and the `RightsAdministrator` who
    escalates an infringement case to legal must not be the same user recorded as
    that case's `triaged_by_user_id`. Either violation is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/shared_reads_and_the_shared_closure_action_admit_every_declared_role
    """
    scenario = _a_takedown_beside_an_active_grant()
    assert scenario["case"]["triaged_by_user_id"] == scenario["compliance_user_id"]

    closed = validate_success(
        api_client.close_infringement_case(
            scenario["case"]["id"],
            factories.close_case_payload("REMOVED"),
            scenario["compliance_headers"],
        ),
        200,
    )

    assert closed["status"] == "RESOLVED_REMOVED"
    assert closed["closure_outcome"] == "VOLUNTARY_REMOVAL"
    assert closed["closed_by_user_id"] == scenario["compliance_user_id"]
    assert closed["legal_hold_applied_count"] == 0


def test_a_missing_or_undeclared_role_header_is_refused_before_any_role_check():
    """Three malformed header shapes and a header-less write all answer 401.

    The PRD states: "Every request must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming that user's role." The
    refusal is the same whichever half is missing, and an unknown role name is
    treated as no role at all rather than as a forbidden one: "If either header is
    absent, or if `X-User-Role` is not one of the five declared roles, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." That rung sits above the
    role rung: "Authentication comes first: the header check that yields
    `ERR_UNAUTHENTICATED`, then the role-authorization check that yields
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/shared_reads_and_the_shared_closure_action_admit_every_declared_role
    """
    scenario = _a_takedown_beside_an_active_grant()
    path = "/consent-grants/" + scenario["grant"]["id"]

    malformed = (
        {"X-User-Role": "RightsAdministrator", "Content-Type": "application/json"},
        {"X-User-ID": scenario["admin_user_id"], "Content-Type": "application/json"},
        build_user_headers(scenario["admin_user_id"], "Notary"),
    )
    for headers in malformed:
        refused = api_client.raw_get(path, headers)
        validate_error(refused, "ERR_UNAUTHENTICATED")
        assert refused.status_code == 401

    headerless = api_client.raw_post("/talents", factories.talent_payload(), {})
    validate_error(headerless, "ERR_UNAUTHENTICATED")
    assert headerless.status_code == 401

    assert _read_the_grant(scenario, scenario["admin_headers"])["status"] == "ACTIVE"


def test_a_role_permitted_caller_still_has_to_get_the_payload_right():
    """A missing name, a spelled-out state and a money string are all malformed.

    The PRD fixes the shape of a talent record: "A `RightsAdministrator` creates
    one by supplying the performer's `legal_name` (1 to 200 characters, not
    blank), the `domicile_state_code` of legal domicile (exactly two uppercase
    letters), and optionally a `union_code`, which is `NONE`, `SAG_AFTRA` or `AFM`
    and defaults to `NONE`." Money has one admissible wire form: "All money in
    this system is held in integer cents, and every monetary field must be sent as
    a JSON number — a monetary amount sent as a string is malformed and draws
    `ERR_INVALID_REQUEST`." All three land on the same rung: "Payload
    well-formedness comes next, yielding `ERR_INVALID_REQUEST` — every required
    field present, every enum value inside its declared set, integers not
    negative, monetary amounts sent as JSON numbers rather than strings, ISO 8601
    datetimes parseable, percentage fields within 0 through 1, required arrays
    non-empty, `limit` within 1 through 100 and `offset` not negative."

    Design: Corner/rbac/shared_reads_and_the_shared_closure_action_admit_every_declared_role
    """
    scenario = _a_takedown_beside_an_active_grant()

    nameless = factories.talent_payload()
    nameless.pop("legal_name")
    spelled_out = factories.talent_payload(domicile_state_code="California")
    fixtures.refresh_talent(scenario)
    money_as_text = factories.consent_grant_payload(
        scenario["talent"]["id"],
        scenario["talent"]["version"],
        initial_creation_fee_cents="300000",
    )

    probes = (
        api_client.raw_post("/talents", nameless, scenario["admin_headers"]),
        api_client.raw_post("/talents", spelled_out, scenario["admin_headers"]),
        api_client.raw_post("/consent-grants", money_as_text, scenario["admin_headers"]),
    )
    for refused in probes:
        validate_error(refused, "ERR_INVALID_REQUEST")
        assert refused.status_code == 400


HADDAD = {"legal_name": "Noor Haddad"}

DIED_IN_JULY = {"date_of_death": "2026-07-01T00:00:00Z"}

HADDAD_ESTATE = {
    "executor_name": "Haddad Estate LLC",
    "court_document_ref": "NY-SURR-2026-0442",
}

HIJACKED_RESUBMISSION = {
    "intended_use_description": "hijacked",
    "projected_impressions": 900_000,
}


def _one_producers_performance_and_a_foreign_estate():
    """Talent A's submitted output, and talent B's verified estate next door."""
    home = fixtures.register_state_law_profile()
    fixtures.create_talent(home)
    fixtures.draft_consent_grant(home, ADVERTISING_GRANT)
    fixtures.countersign_grant(home)
    fixtures.register_biometric_asset(home, VOICE_SAMPLE)
    fixtures.build_replica(home, VOICE_BUILD)
    fixtures.approve_replica(home)
    fixtures.submit_performance(home, US_SPOT)

    away = fixtures.new_scenario()
    fixtures.create_talent(away, HADDAD)
    fixtures.record_death(away, DIED_IN_JULY)
    fixtures.submit_estate_authority(away, HADDAD_ESTATE)
    fixtures.verify_estate_authority(away)
    return home, away


def _review_the_spot(home, headers, note):
    """Send an approval of talent A's output under the supplied headers."""
    return api_client.review_generated_performance(
        home["performance"]["id"],
        factories.review_payload("APPROVE", review_note=note),
        headers,
    )


def _resubmit_the_spot(home, headers):
    """Send a replacement projection for talent A's output."""
    return api_client.resubmit_generated_performance(
        home["performance"]["id"],
        factories.resubmit_payload(**HIJACKED_RESUBMISSION),
        headers,
    )


def test_neither_representative_of_another_principal_may_clear_this_output():
    """Talent B's representative and estate each draw their own ownership error.

    The PRD binds the acting identifier to the row being acted on: "When
    `X-User-Role` is `TalentRepresentative`, `X-User-ID` is the `id` of the acting
    `Talent`; ownership checks on any resource that references a `Talent` compare
    the resource's talent foreign key to `X-User-ID`. A mismatch is
    `ERR_NOT_TALENT_REPRESENTATIVE` (HTTP 403)." Authority over one estate confers
    none over another: "When `X-User-Role` is `EstateRepresentative`, `X-User-ID`
    is the `id` of the acting `EstateAuthority`; ownership checks require that
    authority to be `VERIFIED` and to name, through its own `talent_id`, the talent
    behind the target resource. A mismatch — no such authority, or one that is not
    `VERIFIED`, or one belonging to a different talent — is
    `ERR_NOT_ESTATE_REPRESENTATIVE` (HTTP 403)." The endpoint itself admits both
    roles, so nothing but the binding can be failing here: "The talent side then
    exercises the approval right. A `TalentRepresentative` whose identifier equals
    the talent behind the performance, or an `EstateRepresentative` holding that
    talent's `VERIFIED` estate authority, records a `decision` of `APPROVE`,
    `REQUEST_REVISION` or `REJECT`, with an optional `review_note` stored
    alongside it and, for an outright rejection, a `rejection_reason`."

    Design: Corner/rbac/representatives_cannot_reach_across_to_another_principals_records
    """
    home, away = _one_producers_performance_and_a_foreign_estate()
    baseline = fixtures.refresh_performance(home)

    wrong_talent = _review_the_spot(home, away["talent_rep_headers"], "not my talent")
    validate_error(wrong_talent, "ERR_NOT_TALENT_REPRESENTATIVE")
    assert wrong_talent.status_code == 403

    assert away["estate_authority"]["status"] == "VERIFIED"
    wrong_estate = _review_the_spot(home, away["estate_rep_headers"], "not my estate")
    validate_error(wrong_estate, "ERR_NOT_ESTATE_REPRESENTATIVE")
    assert wrong_estate.status_code == 403

    untouched = fixtures.refresh_performance(home)
    assert untouched["review_status"] == "SUBMITTED"
    assert untouched["reviewed_by_user_id"] is None
    assert untouched["version"] == baseline["version"]


def test_a_second_producer_may_not_resubmit_the_first_producers_performance():
    """The stranger's replacement projection never reaches the row.

    The PRD states: "Resubmission belongs to the licensee. The owning
    `LicenseeProducer` — the one whose identifier equals the performance's
    `licensee_user_id`, or the request draws `ERR_NOT_LICENSEE_OWNER` — supplies a
    replacement `intended_use_description` and a replacement
    `projected_impressions`." That identifier is recorded when the output is
    created: "The server records it as `licensee_user_id` on the generated
    performance that the producer created and copies that value onto every license
    issued from it; ownership checks compare `X-User-ID` to that recorded
    `licensee_user_id` rather than to any entity's `id`, and a mismatch is
    `ERR_NOT_LICENSEE_OWNER` (HTTP 403)."

    Design: Corner/rbac/representatives_cannot_reach_across_to_another_principals_records
    """
    home, _away = _one_producers_performance_and_a_foreign_estate()
    assert home["performance"]["licensee_user_id"] == home["licensee_user_id"]

    stranger = _resubmit_the_spot(home, home["other_licensee_headers"])
    validate_error(stranger, "ERR_NOT_LICENSEE_OWNER")
    assert stranger.status_code == 403

    untouched = fixtures.refresh_performance(home)
    assert untouched["intended_use_description"] == "US spot"
    assert untouched["projected_impressions"] == 500_000
    assert untouched["review_status"] == "SUBMITTED"


def test_the_right_principal_clears_the_same_output_with_the_same_body():
    """After three ownership refusals the fourth identical call is accepted.

    The PRD states: "`APPROVE` moves the performance `SUBMITTED → APPROVED`,
    records `reviewed_by_user_id`, and **retains** the provisional accrual — it is
    reversed only by rejection, withdrawal or resubmission." Nothing else about
    the request changed, and the round counter only moves on a resubmission: "On
    success the performance moves `REVISION_REQUESTED → SUBMITTED`,
    `revision_round` increases by one, the two supplied fields replace their
    predecessors, `reviewed_by_user_id` is cleared to null, and `review_deadline`
    is set afresh to the current logical instant advanced by seven days."

    Design: Corner/rbac/representatives_cannot_reach_across_to_another_principals_records
    """
    home, away = _one_producers_performance_and_a_foreign_estate()
    baseline = fixtures.refresh_performance(home)

    validate_error(
        _review_the_spot(home, away["talent_rep_headers"], "not my talent"),
        "ERR_NOT_TALENT_REPRESENTATIVE",
    )
    validate_error(
        _review_the_spot(home, away["estate_rep_headers"], "not my estate"),
        "ERR_NOT_ESTATE_REPRESENTATIVE",
    )
    validate_error(
        _resubmit_the_spot(home, home["other_licensee_headers"]),
        "ERR_NOT_LICENSEE_OWNER",
    )

    approved = validate_success(
        _review_the_spot(home, home["talent_rep_headers"], "mine to clear"), 200
    )

    assert approved["review_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == home["talent"]["id"]
    assert approved["revision_round"] == 0
    assertions.assert_version_advanced_by(approved, baseline["version"], 1)


VIRAL_DETECTION = {
    "suspect_url": "https://pirate.example/viral",
    "detected_view_count": 10_000_000,
    "match_confidence": 1.000,
}


def _a_filed_claim_and_a_triaged_takedown():
    """An estate claim filed by ra-001, and a case triaged by co-001 at 0.8950."""
    away = fixtures.register_state_law_profile()
    fixtures.create_talent(away, HADDAD)
    fixtures.record_death(away, DIED_IN_JULY)
    fixtures.submit_estate_authority(away, HADDAD_ESTATE)

    home = fixtures.new_scenario()
    fixtures.create_talent(home)
    fixtures.open_case(home, VIRAL_DETECTION)
    fixtures.triage_case(home, "ISSUE_TAKEDOWN")
    return home, away


def _verify_the_claim(away, headers):
    """Send the verification of the filed claim under the supplied headers."""
    return api_client.verify_estate_authority(away["estate_authority"]["id"], {}, headers)


def test_the_administrator_who_filed_the_claim_may_not_be_the_one_who_verifies_it():
    """The filer is refused, the second pair of hands is accepted.

    The PRD states: "Verification is a second `RightsAdministrator`'s act. It is
    refused with `ERR_INVALID_ESTATE_AUTHORITY_STATE` unless the claim's `status`
    is `SUBMITTED`, so an already `VERIFIED` or `REJECTED` claim cannot be verified
    again, and it is refused with `ERR_SEGREGATION_OF_DUTIES` when the verifying
    user is the same user recorded as `submitted_by_user_id`." What acceptance
    changes is exact: "On success the claim's `status` becomes `VERIFIED`,
    `verified_by_user_id` records the verifier and `verified_at` records the
    logical instant. The talent's `postmortem_registration_number` is then copied
    from this authority's `registration_number`, so a state that demands
    registration can be satisfied from the estate paperwork."

    Design: Corner/rbac/escalation_and_estate_verification_each_demand_a_second_pair_of_hands
    """
    _home, away = _a_filed_claim_and_a_triaged_takedown()
    assert away["estate_authority"]["submitted_by_user_id"] == away["admin_user_id"]

    same_hands = _verify_the_claim(away, away["admin_headers"])
    validate_error(same_hands, "ERR_SEGREGATION_OF_DUTIES")
    assert same_hands.status_code == 403

    still_filed = validate_success(
        api_client.get_estate_authority(
            away["estate_authority"]["id"], away["admin_headers"]
        ),
        200,
    )
    assert still_filed["status"] == "SUBMITTED"
    assert still_filed["verified_at"] is None
    assert fixtures.read_talent(away)["postmortem_registration_number"] is None

    verified = validate_success(_verify_the_claim(away, away["second_admin_headers"]), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == away["second_admin_user_id"]
    assert fixtures.read_talent(away)["postmortem_registration_number"] == "CA-REG-77"


def test_the_triaging_officers_identifier_bars_escalation_whatever_role_it_wears():
    """The bar compares the recorded id, so an administrator reusing it is refused.

    The PRD states: "Two duties in this office are deliberately segregated, and
    both are enforced by comparing recorded operator identifiers. The
    `RightsAdministrator` who verifies an estate authority must not be the same
    user recorded as that authority's `submitted_by_user_id`, and the
    `RightsAdministrator` who escalates an infringement case to legal must not be
    the same user recorded as that case's `triaged_by_user_id`. Either violation is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." The severity floor is not what bites,
    because this case clears it: "Its `severity_score` must be at least 0.5000, or
    escalation is refused with `ERR_SEVERITY_BELOW_ESCALATION_FLOOR` — the
    sweep-opened case scoring 0.6900 clears that floor while the 0.3550 case does
    not." The identifier compared is the one the triage recorded: "And the
    escalating administrator must not be the officer recorded as
    `triaged_by_user_id`, or the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES`." Acceptance is destructive by design: "Hop one
    moves the case `TAKEDOWN_ISSUED → LEGAL_ESCALATED` and records
    `escalated_by_user_id`."

    Design: Corner/rbac/escalation_and_estate_verification_each_demand_a_second_pair_of_hands
    """
    home, _away = _a_filed_claim_and_a_triaged_takedown()
    assert home["case"]["severity_score"] == 0.8950
    assert home["case"]["triaged_by_user_id"] == home["compliance_user_id"]

    same_hands = api_client.escalate_infringement_case(
        home["case"]["id"],
        factories.escalate_payload(),
        make_rights_administrator_headers(home["compliance_user_id"]),
    )
    validate_error(same_hands, "ERR_SEGREGATION_OF_DUTIES")
    assert same_hands.status_code == 403

    held = fixtures.refresh_case(home)
    assert held["status"] == "TAKEDOWN_ISSUED"
    assert held["escalated_by_user_id"] is None
    assertions.assert_posture(fixtures.read_talent(home), "CLEAR")

    escalated = fixtures.escalate_case(home)
    assert escalated["status"] == "LEGAL_ESCALATED"
    assert escalated["escalated_by_user_id"] == home["second_admin_user_id"]
    assertions.assert_posture(fixtures.read_talent(home), "FROZEN")
