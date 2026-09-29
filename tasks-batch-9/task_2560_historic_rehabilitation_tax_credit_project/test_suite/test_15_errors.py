"""Refusals: one per declared error condition, each with its own witness.

Unknown ids on the remaining seven reads, the two part-sequencing guards, an
amendment aimed at the wrong application's finding, the two structure guards on
admission, three replays refused on entity state, the compliance-period guard, the
lock that Part 3 certification puts on costs, the claim-year guards, and the two
investor-standing refusals.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)

UNKNOWN_FINDING_ID = "00000000-0000-0000-0000-000000000001"
UNKNOWN_COST_ITEM_ID = "00000000-0000-0000-0000-000000000002"
UNKNOWN_AMENDMENT_ID = "00000000-0000-0000-0000-000000000003"
UNKNOWN_INTEREST_ID = "00000000-0000-0000-0000-000000000004"
UNKNOWN_CLAIM_ID = "00000000-0000-0000-0000-000000000005"
UNKNOWN_COVENANT_ID = "00000000-0000-0000-0000-000000000006"
UNKNOWN_EVENT_ID = "00000000-0000-0000-0000-000000000007"


def test_each_remaining_entity_read_reports_its_own_not_found_error(api):
    """Seven reads against an empty database, seven distinct 404 error ids.

    Nothing has been created, so every one of these ids is dangling. Each read
    reports the not-found error of the entity that owns the path rather than a
    shared generic one, and every refusal comes back in the error envelope with a
    human-readable message.

    PRD: "Each `{id}` in the path resolves to an existing row of its entity, else that entity's own not-found error (404)."
    PRD: "All error API responses (4xx status codes) follow this standard envelope format:"
    PRD: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/remaining_entity_reads_with_unknown_id_return_not_found
    """
    reads = (
        (api.get_finding(UNKNOWN_FINDING_ID, fixtures.ADMIN),
         ApiErrorId.STANDARD_FINDING_NOT_FOUND.value),
        (api.get_cost_line_item(UNKNOWN_COST_ITEM_ID, fixtures.ADMIN),
         ApiErrorId.COST_LINE_ITEM_NOT_FOUND.value),
        (api.get_amendment(UNKNOWN_AMENDMENT_ID, fixtures.ADMIN),
         ApiErrorId.AMENDMENT_NOT_FOUND.value),
        (api.get_investor_interest(UNKNOWN_INTEREST_ID, fixtures.ADMIN),
         ApiErrorId.INVESTOR_INTEREST_NOT_FOUND.value),
        (api.get_credit_claim(UNKNOWN_CLAIM_ID, fixtures.ADMIN),
         ApiErrorId.CREDIT_CLAIM_NOT_FOUND.value),
        (api.get_compliance_covenant(UNKNOWN_COVENANT_ID, fixtures.ADMIN),
         ApiErrorId.COMPLIANCE_COVENANT_NOT_FOUND.value),
        (api.get_recapture_event(UNKNOWN_EVENT_ID, fixtures.ADMIN),
         ApiErrorId.RECAPTURE_EVENT_NOT_FOUND.value),
    )

    for response, expected_error_id in reads:
        error = validate_error(response, expected_error_id, 404)
        assert response.json()["response_type"] == "error", (
            "{0} must be reported in the error envelope".format(expected_error_id)
        )
        assert error["message"].strip(), (
            "{0} must carry a human-readable message".format(expected_error_id)
        )


def test_a_part_two_application_cannot_jump_ahead_of_part_one(api):
    """With no Part 1 on the project at all, Part 2 has nothing to follow.

    The project has just been opened and carries no part application of any number,
    so the Part 1 predecessor has reached neither CONDITIONAL nor APPROVED. Applying
    for Part 2 is refused as a sequencing violation: no application row is written,
    the certification dimension is still at PRE_CERTIFICATION, and the project is
    still on the version the refused request quoted.

    PRD: "Part 2 requires the project's Part 1 application to have reached `CONDITIONAL` or `APPROVED`, and Part 3 requires the same of Part 2; Part 1 has no predecessor."
    PRD: "A request that jumps the queue is refused with `ERR_PART_SEQUENCE_VIOLATION`."
    PRD: "The project opens with `certification_status` at `PRE_CERTIFICATION` and `compliance_status` at `NOT_MONITORED`, with `placed_in_service_date` null, and with the whole credit ledger — `qre_total_final_cents`, `qre_total_provisional_cents`, `nonqualified_total_cents`, `classified_cost_total_cents`, `developer_fee_disallowed_cents`, `annual_credit_cents`, `total_claimable_credit_cents`, `credit_claimed_to_date_cents`, `credit_recaptured_cents`, `credit_unclaimed_cents`, `recapture_balance_cents`, `max_investor_risk_score` — at zero, with `substantial_test_status` at `NOT_MET` and `frozen_at_certification` false."

    Design: Corner/errors/part_two_creation_without_a_cleared_part_one_returns_sequence_violation
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )

    response = api.create_part_application(
        cast.developer_headers,
        **factories.part_application_payload(project["id"], 2, project["version"]),
    )

    validate_error(response, ApiErrorId.PART_SEQUENCE_VIOLATION.value, 422)
    assertions.assert_page(
        api.list_part_applications(cast.developer_headers, project_id=project["id"]),
        total_count=0,
    )
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(stored, certification_status="PRE_CERTIFICATION")
    assertions.assert_fields(
        stored, "project after the refused application", version=1
    )


def test_an_approved_part_cannot_be_applied_for_a_second_time(api):
    """Part 1 is closed by its approval, so a second Part 1 is refused.

    The first application was approved, which certified the building and advanced the
    project to PART1_CERTIFIED. An APPROVED row is never superseded, so applying for
    Part 1 again is refused rather than forking a new attempt: the single existing row
    keeps its APPROVED status and its null supersedes reference, and the project's
    certification dimension and version are untouched.

    PRD: "`APPROVED` and `SUPERSEDED` rows are never superseded: once a part is `APPROVED` it is closed, and a further application for it is refused with `ERR_PART_ALREADY_CERTIFIED`."
    PRD: "When no such row existed, `supersedes_application_id` stays null."
    PRD: "The second hop advances the project's certification dimension according to the part number: `PRE_CERTIFICATION → PART1_CERTIFIED` for Part 1, `PART1_CERTIFIED → PART2_APPROVED` for Part 2, and `PART2_APPROVED → PART3_CERTIFIED` for Part 3, bumping the project's `version`."

    Design: Corner/errors/duplicate_part_one_application_after_approval_returns_already_certified
    """
    scenario = fixtures.part1_certified_project(
        api, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    before = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(before, certification_status="PART1_CERTIFIED")

    response = api.create_part_application(
        cast.developer_headers,
        **factories.part_application_payload(project_id, 1, before["version"]),
    )

    validate_error(response, ApiErrorId.PART_ALREADY_CERTIFIED.value, 409)
    assertions.assert_page(
        api.list_part_applications(
            cast.developer_headers, project_id=project_id, part_number=1
        ),
        total_count=1,
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(scenario["part1"]["id"], cast.developer_headers)
        ),
        "the approved part 1",
        status="APPROVED",
        supersedes_application_id=None,
    )
    after = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(after, certification_status="PART1_CERTIFIED")
    assertions.assert_fields(
        after, "project after the refused application", version=before["version"]
    )


def test_an_amendment_cannot_clear_a_finding_raised_on_another_application(api):
    """The condition belongs to Part 1, and the amendment amends Part 2.

    Part 1 came back CONDITIONAL with one unresolved condition against it, and Part 2
    has been drafted while that condition is worked off. Aiming the Part 2 amendment at
    the Part 1 finding is refused, because an amendment may only clear a finding raised
    against the application whose scope it amends. Nothing is drafted, the finding is
    still unresolved and still recorded against Part 1, and Part 2 is still in DRAFT.

    PRD: "A finding raised against a different application than the one being amended is refused with `ERR_AMENDMENT_FINDING_MISMATCH` — an amendment may only clear a finding raised against the very application whose scope it amends."
    PRD: "Either agency's reviewer may raise findings against an application while it is under review — that is, while its status is `SHPO_REVIEW`, `NPS_REVIEW`, or `CONDITIONAL`; a finding against an application in any other status is refused with `ERR_PART_APPLICATION_INVALID_STATE`."
    PRD: "A new finding starts with `resolution_state` of `UNRESOLVED`."
    PRD: "Creation is deliberately permitted on a merely `CONDITIONAL` predecessor so that the developer can prepare the next part while conditions are being cleared by amendment — but that next part cannot enter review until the building itself is certified, which only an `APPROVED` Part 1 produces."

    Design: Corner/errors/amendment_addressing_a_finding_from_another_application_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    part1 = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, part1["id"])
    fixtures.shpo_recommend(api, cast, part1["id"])
    finding = fixtures.add_finding(
        api,
        cast,
        part1["id"],
        standard_number=2,
        severity="CONDITION",
        description="The mortar mix must match the historic lime-rich profile.",
    )
    fixtures.nps_determine(api, cast, part1["id"], determination="CONDITIONAL")
    part2 = fixtures.create_part_application(api, cast, project["id"], 2)

    response = api.create_amendment(
        cast.developer_headers,
        **factories.amendment_payload(
            project["id"],
            part2["id"],
            scope_category="MASONRY_TREATMENT",
            change_description="Mortar mix revised to a lime-rich historic profile.",
            cost_delta_cents=200_000,
            addresses_finding_id=finding["id"],
        ),
    )

    validate_error(response, ApiErrorId.AMENDMENT_FINDING_MISMATCH.value, 422)
    assertions.assert_page(
        api.list_amendments(cast.developer_headers, project_id=project["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        validate_success(api.get_finding(finding["id"], cast.shpo_headers)),
        "the part 1 condition",
        resolution_state="UNRESOLVED",
        part_application_id=part1["id"],
    )
    assertions.assert_fields(
        get_success_data(api.get_part_application(part2["id"], cast.developer_headers)),
        "the drafted part 2",
        status="DRAFT",
    )


def test_a_master_lease_project_refuses_a_direct_partner_interest(api):
    """The structure elected at opening decides which kind of interest is admissible.

    The project elected MASTER_LEASE, which admits master-lease lessees only, so an
    interest whose kind is DIRECT_PARTNER is a structure mismatch. It is refused, the
    project still has no interest of any kind, and with nothing admitted the standing
    maximum risk score is zero.

    PRD: "A `MASTER_LEASE` project admits exactly one `MASTER_LEASE_LESSEE` interest and requires `lease_term_years` on it; a `SINGLE_TIER` project admits only `DIRECT_PARTNER` interests and rejects `lease_term_years` outright."
    PRD: "A mismatched `kind`, a missing or forbidden lease term, or a second master-lease lessee is refused with `ERR_STRUCTURE_TYPE_MISMATCH`."
    PRD: "The project's `max_investor_risk_score` is the maximum `disqualification_risk_score` across its `ADMITTED` interests, and zero when the project has no `ADMITTED` interest at all."

    Design: Corner/errors/direct_partner_interest_on_master_lease_project_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )

    response = api.create_investor_interest(
        cast.developer_headers,
        **factories.investor_interest_payload(
            project["id"],
            kind="DIRECT_PARTNER",
            party_legal_name="Buckeye Credit Fund Inc",
            party_tax_status="TAXABLE_C_CORP",
            capital_committed_cents=12_000_000,
            credit_allocation_pct=50.0,
        ),
    )

    validate_error(response, ApiErrorId.STRUCTURE_TYPE_MISMATCH.value, 422)
    assertions.assert_page(
        api.list_project_investor_interests(project["id"], cast.developer_headers),
        total_count=0,
    )
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_fields(
        stored, "master-lease project", structure_type="MASTER_LEASE"
    )
    assertions.assert_ledger(stored, max_investor_risk_score=0)


def test_a_tax_exempt_master_tenant_is_refused_as_a_disqualified_party(api):
    """A tax-exempt lessee cannot use the credit, so it is turned away at admission.

    The party's tax status is TAX_EXEMPT_ORG, which disqualifies the credit outright
    however sound the rest of the interest is. On a two-year lease the admission score
    would be 69 — the base 10, 45 for the tax status, 2 of the 30 lease points and 12
    for the pending election — so it is the party's status and not its risk that
    refuses the admission. No interest is recorded and the project's standing maximum
    risk score stays at zero.

    PRD: "A master-lease lessee whose `party_tax_status` is `TAX_EXEMPT_ORG` or `GOVERNMENTAL_UNIT` disqualifies the credit outright and is refused with `ERR_DISQUALIFIED_PARTY`."
    PRD: "Its `party_tax_status` adds points on a fixed scale: nothing for `TAXABLE_C_CORP`, 10 points for `PARTNERSHIP`, 35 points for `GOVERNMENTAL_UNIT`, and 45 points for `TAX_EXEMPT_ORG`."
    PRD: "An admission whose `ADMISSION`-variant score reaches 70 is refused with `ERR_DISQUALIFICATION_RISK_TOO_HIGH`, and the same error blocks the filing of a credit claim when the project's standing `max_investor_risk_score` has reached 70 by the time of filing."

    Design: Corner/errors/tax_exempt_master_lease_lessee_rejected_as_disqualified_party
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )

    response = api.create_investor_interest(
        cast.developer_headers,
        **factories.master_lease_interest_payload(
            project["id"],
            party_legal_name="Dayton Heritage Trust",
            party_tax_status="TAX_EXEMPT_ORG",
            capital_committed_cents=12_000_000,
            credit_allocation_pct=50.0,
            lease_term_years=2,
        ),
    )

    validate_error(response, ApiErrorId.DISQUALIFIED_PARTY.value, 422)
    assertions.assert_page(
        api.list_project_investor_interests(project["id"], cast.developer_headers),
        total_count=0,
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]), max_investor_risk_score=0
    )


def test_the_building_cannot_be_declared_placed_in_service_twice(api):
    """The pivot fires exactly once, so the second declaration is a replay.

    The building was declared placed in service on 2029-01-15, which opened the
    monitoring dimension. A second declaration naming a later date is refused as an
    invalid state rather than moving the date: the recorded date, both dimensions and
    the project's version are all exactly as the first declaration left them.

    PRD: "It may be declared exactly once: a second declaration, or a declaration on a project that is `PART3_CERTIFIED` or `DECERTIFIED` and therefore no longer editable, is refused with `ERR_PROJECT_INVALID_STATE`."
    PRD: "This band also catches idempotent replays — a second request for the same action on an already-advanced row."
    PRD: "On success the compliance dimension moves `NOT_MONITORED → IN_SERVICE_MONITORING`, every `ADMITTED` investor interest is re-scored under the `IN_SERVICE` variant, `max_investor_risk_score` is refreshed from those scores, and the project's `version` increments."

    Design: Corner/errors/place_in_service_declared_twice_returns_project_invalid_state
    """
    scenario = fixtures.in_service_project(
        api, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    before = fixtures.read_project(api, cast, project_id)
    assertions.assert_fields(
        before, "project after the first declaration",
        placed_in_service_date="2029-01-15",
    )

    response = api.place_in_service(
        project_id, cast.developer_headers, placed_in_service_date="2029-03-01"
    )

    validate_error(response, ApiErrorId.PROJECT_INVALID_STATE.value, 409)
    after = fixtures.read_project(api, cast, project_id)
    assertions.assert_fields(
        after,
        "project after the refused second declaration",
        placed_in_service_date="2029-01-15",
        version=before["version"],
    )
    assertions.assert_project_state(
        after,
        certification_status="PART2_APPROVED",
        compliance_status="IN_SERVICE_MONITORING",
    )


def test_an_amendment_cannot_be_concurred_before_it_is_submitted(api):
    """Concurrence is declared from SUBMITTED, and this amendment is still DRAFT.

    The amendment has been drafted against the Part 2 application but never submitted,
    so there is no submitted amendment for the state office to concur in. The decision
    is refused on state grounds and writes nothing at all: the amendment is still in
    DRAFT with both verdicts at NONE, still needs no federal concurrence, and is still
    on its first version.

    PRD: "The requested transition is declared from the target's current state, else that entity's invalid-state error (`ERR_PART_APPLICATION_INVALID_STATE`, `ERR_AMENDMENT_INVALID_STATE`, `ERR_COVENANT_INVALID_STATE`, `ERR_PROJECT_INVALID_STATE`, all 409), together with the other state-shaped preconditions: `ERR_CREDIT_CLAIM_ALREADY_FILED`, `ERR_PROJECT_NOT_CERTIFIED`, `ERR_PROJECT_NOT_PLACED_IN_SERVICE`, `ERR_COST_ITEM_LOCKED` (409) and `ERR_ELECTION_WINDOW_CLOSED` (422)."
    PRD: "When `requires_nps_concurrence` is false, a `CONCUR` from an `ACTIVE` `SHPO` reviewer joins immediately: the amendment moves `SUBMITTED → CONCURRED` and `shpo_decision` becomes `CONCUR`."
    PRD: "The amendment begins in `DRAFT` with `shpo_decision` and `nps_decision` both `NONE` and `submitted_at` null."

    Design: Corner/errors/amendment_concurrence_before_submission_returns_amendment_invalid_state
    """
    scenario = fixtures.part1_certified_project(
        api, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    part2 = fixtures.create_part_application(api, cast, project_id, 2)
    amendment = validate_success(
        api.create_amendment(
            cast.developer_headers,
            **factories.amendment_payload(
                project_id,
                part2["id"],
                scope_category="MASONRY_TREATMENT",
                change_description="Repointing profiles revised for the north wall.",
                cost_delta_cents=200_000,
            ),
        ),
        201,
    )

    response = api.concur_amendment(
        amendment["id"],
        cast.shpo_headers,
        decision="CONCUR",
        concurrence_note="Profiles acceptable.",
    )

    validate_error(response, ApiErrorId.AMENDMENT_INVALID_STATE.value, 409)
    assertions.assert_fields(
        get_success_data(api.get_amendment(amendment["id"], cast.developer_headers)),
        "amendment after the refused concurrence",
        status="DRAFT",
        shpo_decision="NONE",
        nps_decision="NONE",
        requires_nps_concurrence=False,
        submitted_at=None,
        version=1,
    )


def test_a_cure_attestation_arriving_after_the_deadline_is_refused(api):
    """The cure deadline is 2029-05-01, and this attestation is for 2029-05-10.

    The covenant window closed on 2029-01-31 and that period was attested as an
    exception, which breached the covenant and set the cure deadline ninety days after
    the window end. A satisfied attestation for a period ending after that deadline is
    too late to cure: it is refused, the covenant stays BREACHED with its one exception
    and its one attestation, its last attested period is still the breached one, and
    the project is still parked in CURE_PENDING.

    PRD: "Curing is time-boxed."
    PRD: "A `SATISFIED` attestation on a `BREACHED` covenant moves it `BREACHED → CURED`, but only when the attested `period_end_date` falls on or before `cure_deadline_date`; a cure attestation arriving after that deadline is refused with `ERR_COVENANT_INVALID_STATE`."
    PRD: "From `PENDING_ATTESTATION`, `COMPLIANT`, or `CURED`, the covenant moves to `BREACHED`; `exception_count` rises by one alongside `attestation_count`, and `cure_deadline_date` is set to `window_end_date` advanced by ninety days."

    Design: Corner/errors/covenant_cure_attestation_after_the_cure_deadline_returns_covenant_invalid_state
    """
    scenario = fixtures.in_service_project(
        api, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2029-01-31",
    )
    breached = fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-01-31", "EXCEPTION"
    )
    assertions.assert_fields(
        breached, "breached covenant", status="BREACHED",
        cure_deadline_date="2029-05-01",
    )
    fixtures.set_clock(api, "2029-05-10T00:00:00Z")

    response = api.attest_covenant(
        covenant["id"],
        cast.developer_headers,
        period_end_date="2029-05-10",
        outcome="SATISFIED",
    )

    validate_error(response, ApiErrorId.COVENANT_INVALID_STATE.value, 409)
    assertions.assert_fields(
        get_success_data(
            api.get_compliance_covenant(covenant["id"], cast.developer_headers)
        ),
        "covenant after the late cure",
        status="BREACHED",
        cure_deadline_date="2029-05-01",
        exception_count=1,
        attestation_count=1,
        last_attested_period_end="2029-01-31",
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project_id),
        compliance_status="CURE_PENDING",
    )


def test_a_recapture_event_five_full_years_after_the_pivot_is_out_of_period(api):
    """2034-02-01 is five whole years past a 2029-01-15 placed-in-service date.

    Counting a year as 365 days, the elapsed whole years from the pivot to the event
    date are five, and the compliance period requires strictly fewer than five. The
    report is refused, no event row is written, and the project's compliance posture,
    outstanding recapture balance and version are all untouched.

    PRD: "The event must fall inside the compliance period: its `event_date` must be on or after the project's `placed_in_service_date`, and its `full_years_elapsed` must be strictly less than five, else `ERR_RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD`."
    PRD: "`full_years_elapsed` is the number of days from the project's `placed_in_service_date` to the event's `event_date`, divided by 365 and truncated downward to a whole number."
    PRD: "The assessment itself runs before anything is persisted."

    Design: Corner/errors/recapture_event_after_the_five_year_period_returns_outside_compliance_period
    """
    scenario = fixtures.in_service_project(
        api, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    before = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(before, compliance_status="IN_SERVICE_MONITORING")
    fixtures.set_clock(api, "2034-02-01T00:00:00Z")

    response = api.create_recapture_event(
        fixtures.MONITOR,
        project_id=project_id,
        event_type="CESSATION_OF_USE",
        event_date="2034-02-01",
    )

    validate_error(response, ApiErrorId.RECAPTURE_OUTSIDE_COMPLIANCE_PERIOD.value, 422)
    assertions.assert_page(
        api.list_project_recapture_events(project_id, fixtures.MONITOR),
        total_count=0,
    )
    after = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(after, compliance_status="IN_SERVICE_MONITORING")
    assertions.assert_ledger(
        after, recapture_balance_cents=0, version=before["version"]
    )


def test_the_developer_cannot_reclassify_a_cost_locked_by_part_three(api):
    """Part 3 certification locked the item, and only an auditor may move it now.

    The 60000000 of qualified construction exactly meets the 60000000 threshold, so the
    project certified through Part 3, which froze the schedule at 2400000 a year and
    12000000 in total and drove the item from QRE to LOCKED_QRE. The developer's
    attempt to push it onto the non-qualified side is refused: the item keeps its locked
    qualified classification, its NONE exclusion reason and its untouched
    reclassification count, and the project's frozen ledger is exactly as certification
    left it.

    PRD: "On Part 3 certification every `QRE` item becomes `LOCKED_QRE` and every `NON_QRE` item becomes `LOCKED_NON_QRE`, and a `Developer` who then attempts to reclassify one is refused with `ERR_COST_ITEM_LOCKED`."
    PRD: "Only a `ComplianceMonitor` can move a locked item, and only in one direction: an audit disallowance takes it `LOCKED_QRE → LOCKED_NON_QRE`, raising `reclassification_count`, setting `exclusion_reason` to `REVIEWER_DISALLOWED`, and bumping both the item's and the project's `version`."
    PRD: "For Part 3 only, a third hop sets `frozen_at_certification` to true, which permanently stops recomputation of `annual_credit_cents` and `total_claimable_credit_cents`, and drives every cost line item of the project from `QRE` to `LOCKED_QRE` and from `NON_QRE` to `LOCKED_NON_QRE`, bumping each of those line items' `version`."

    Design: Corner/errors/developer_reclassification_after_part3_certification_returns_cost_item_locked
    """
    scenario = fixtures.part3_certified_project(
        api,
        qre_cents=60_000_000,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
    )
    cast = scenario["cast"]
    item_id = scenario["cost"]["id"]

    response = api.classify_cost_line_item(
        item_id,
        cast.developer_headers,
        classification="NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
    )

    validate_error(response, ApiErrorId.COST_ITEM_LOCKED.value, 409)
    assertions.assert_fields(
        get_success_data(api.get_cost_line_item(item_id, cast.developer_headers)),
        "locked qualified item",
        classification="LOCKED_QRE",
        exclusion_reason="NONE",
        reclassification_count=0,
    )
    stored = fixtures.read_project(api, cast, scenario["project"]["id"])
    assertions.assert_project_state(stored, certification_status="PART3_CERTIFIED")
    assertions.assert_substantial_test(stored, "MET", threshold_cents=60_000_000)
    assertions.assert_ratable_schedule(stored, 2_400_000)
    assertions.assert_ledger(
        stored,
        qre_total_final_cents=60_000_000,
        total_claimable_credit_cents=12_000_000,
        frozen_at_certification=True,
    )


def test_the_claim_year_must_be_inside_the_window_and_may_be_claimed_once(api):
    """2034 is a year too late, 2029 opens the window, and 2029 twice is a duplicate.

    The building went into service on 2029-01-15, so the ratable claiming window runs
    from 2029 through 2033 and 2034 falls outside it. The first tax year inside the
    window is accepted and snapshots the project's 2400000 annual credit as the first
    claim of the project, opening in DRAFT with nothing filed. Repeating that same year
    is refused as a duplicate, so the project still has exactly one claim. The claiming
    partnership on its twenty-year lease scores 51 at admission: the base 10, 10 for the
    partnership, 19 of the 30 lease points and 12 for the election still pending.

    PRD: "The `tax_year` must fall inside the ratable claiming window, which runs from the calendar year of `placed_in_service_date` through that year plus four, inclusive — five years in all; a year outside it is refused with `ERR_CLAIM_YEAR_OUT_OF_WINDOW`."
    PRD: "Only one claim may exist per project per tax year regardless of that claim's status, so a duplicate is refused with `ERR_CLAIM_YEAR_DUPLICATE`."
    PRD: "`claim_sequence` is the claim's one-based position among the project's claims ordered by `tax_year` ascending — ties are impossible, since `tax_year` is unique per project."
    PRD: "The claim opens with `status` of `DRAFT`, `recapture_offset_cents` and `net_claim_cents` at zero, and `filed_at` and `filed_by_user_id` null."

    Design: Corner/errors/claim_year_window_and_duplicate_year_guards_both_reject
    """
    scenario = fixtures.part3_certified_project(
        api,
        qre_cents=60_000_000,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    interest = validate_success(
        api.create_investor_interest(
            cast.developer_headers,
            **factories.master_lease_interest_payload(
                project_id,
                party_legal_name="Buckeye Credit Fund LP",
                party_tax_status="PARTNERSHIP",
                capital_committed_cents=40_000_000,
                credit_allocation_pct=100.0,
                lease_term_years=20,
            ),
        ),
        201,
    )
    headers = fixtures.investor_headers(interest)

    too_late = api.create_credit_claim(headers, project_id=project_id, tax_year=2034)
    opened = api.create_credit_claim(headers, project_id=project_id, tax_year=2029)
    repeated = api.create_credit_claim(headers, project_id=project_id, tax_year=2029)

    validate_error(too_late, ApiErrorId.CLAIM_YEAR_OUT_OF_WINDOW.value, 422)
    claim = validate_success(opened, 201)
    validate_error(repeated, ApiErrorId.CLAIM_YEAR_DUPLICATE.value, 409)
    assertions.assert_fields(
        claim,
        "the first claim",
        tax_year=2029,
        claim_sequence=1,
        gross_credit_cents=2_400_000,
        status="DRAFT",
        filed_at=None,
    )
    assertions.assert_page(
        api.list_project_credit_claims(project_id, cast.developer_headers),
        total_count=1,
    )
    stored_interest = validate_success(
        api.get_investor_interest(interest["id"], cast.developer_headers)
    )
    assertions.assert_fields(stored_interest, "claiming lessee", status="ADMITTED")
    assertions.assert_risk_score(stored_interest, 51, "ADMISSION")


def test_a_lessee_disqualified_by_an_ownership_transfer_cannot_open_a_claim(api):
    """The transfer strips the master tenant of its standing to claim anything.

    The monitor reports an ownership transfer four and a half months after the building
    went into service, which is inside the compliance period and so is assessed with
    zero whole years elapsed and recorded as a reported event. The transfer drives the
    project's compliance dimension to the absorbing RECAPTURED and disqualifies the
    admitted master tenant. The disqualified interest can no longer open a claim, which
    surfaces as a standing refusal rather than a project-state one, and no claim row is
    written.

    PRD: "When a recapture event of `LEASE_TO_DISQUALIFIED` or `OWNERSHIP_TRANSFER` type is reported against the project, every `ADMITTED` interest whose `kind` is `MASTER_LEASE_LESSEE` moves `ADMITTED → DISQUALIFIED`, its `version` increments, and the project's `max_investor_risk_score` is refreshed over the interests that remain `ADMITTED`."
    PRD: "A `DISQUALIFIED` interest can no longer open or file credit claims, which surfaces as `ERR_INVESTOR_NOT_ADMITTED`."
    PRD: "The event is persisted with `status` of `ASSESSED` and `source` of `REPORTED` for a monitor's report, or `SYSTEM_DERIVED` for one the system raises itself, and the amount is added to the project's `recapture_balance_cents`."
    PRD: "Because the identity is the interest itself, a claim action succeeds only when the acting interest's `project_id` equals the claim's `project_id` and the interest's `status` is `ADMITTED`; a mismatch or a `DISQUALIFIED` interest is refused with `ERR_INVESTOR_NOT_ADMITTED` (HTTP 403)."

    Design: Corner/errors/claim_creation_by_a_disqualified_lessee_returns_investor_not_admitted
    """
    scenario = fixtures.part3_certified_project(
        api,
        qre_cents=60_000_000,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    interest = fixtures.admit_master_lease_lessee(
        api,
        cast,
        project_id,
        elect=False,
        party_legal_name="Buckeye Credit Fund LP",
        party_tax_status="PARTNERSHIP",
        credit_allocation_pct=100.0,
        lease_term_years=20,
    )
    fixtures.set_clock(api, "2029-06-01T00:00:00Z")
    event = fixtures.report_recapture_event(
        api, project_id, "OWNERSHIP_TRANSFER", "2029-06-01"
    )

    response = api.create_credit_claim(
        fixtures.investor_headers(interest), project_id=project_id, tax_year=2029
    )

    validate_error(response, ApiErrorId.INVESTOR_NOT_ADMITTED.value, 403)
    assertions.assert_fields(
        event, "reported transfer", full_years_elapsed=0, source="REPORTED"
    )
    assertions.assert_fields(
        validate_success(
            api.get_investor_interest(interest["id"], cast.developer_headers)
        ),
        "the former master tenant",
        status="DISQUALIFIED",
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project_id), compliance_status="RECAPTURED"
    )
    assertions.assert_page(
        api.list_project_credit_claims(project_id, cast.developer_headers),
        total_count=0,
    )


def test_a_claim_cannot_be_filed_once_the_in_service_score_reaches_seventy(api):
    """The breach lifts the master tenant's score to exactly the disqualifying 70.

    On a thirty-one-year lease the term reaches the safe harbour, so the tenant takes
    all 30 lease points and is admitted at 62: the base 10, 10 for the partnership, 30
    for the lease and 12 while the election is pending. Electing the pass-through drops
    that penalty to 50. The breached covenant then re-scores the interest under the
    in-service variant, whose 20-point adder for the breach takes it to exactly 70 —
    the disqualifying threshold — and lifts the project's standing maximum with it.
    Filing is refused on that score, and the claim is left in DRAFT with nothing filed
    and its snapshot gross intact.

    PRD: "A score of 70 or more is disqualifying."
    PRD: "The project's `max_investor_risk_score` must be below 70 (`ERR_DISQUALIFICATION_RISK_TOO_HIGH`)."
    PRD: "The `IN_SERVICE` variant, applied to every `ADMITTED` interest of a project whose compliance dimension has left `NOT_MONITORED`, adds a project-level adder on top of the base score: 20 points for each `BREACHED` covenant of the project, plus 10 points for each unresolved preservation violation, counting the total of `unresolved_violation_count` over the project's applications whose status is not `SUPERSEDED`."
    PRD: "A new claim snapshots the project's per-year credit: `gross_credit_cents` is set to the project's `annual_credit_cents` as it stands at claim creation, and it is deliberately **not** re-read at filing time."

    Design: Corner/errors/claim_filing_at_the_in_service_risk_threshold_returns_risk_too_high
    """
    scenario = fixtures.part3_certified_project(
        api,
        qre_cents=60_000_000,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    admitted = validate_success(
        api.create_investor_interest(
            cast.developer_headers,
            **factories.master_lease_interest_payload(
                project_id,
                party_legal_name="Buckeye Credit Fund LP",
                party_tax_status="PARTNERSHIP",
                capital_committed_cents=40_000_000,
                credit_allocation_pct=100.0,
                lease_term_years=31,
            ),
        ),
        201,
    )
    assertions.assert_risk_score(admitted, 62, "ADMISSION")
    headers = fixtures.investor_headers(admitted)
    validate_success(api.elect_pass_through(admitted["id"], headers))
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2029-01-31",
    )
    fixtures.attest_covenant(api, cast, covenant["id"], "2029-01-31", "EXCEPTION")
    claim = fixtures.create_claim(api, admitted, project_id, tax_year=2029)

    response = api.file_credit_claim(claim["id"], headers)

    validate_error(response, ApiErrorId.DISQUALIFICATION_RISK_TOO_HIGH.value, 422)
    stored_interest = validate_success(
        api.get_investor_interest(admitted["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored_interest,
        "the elected master tenant",
        status="ADMITTED",
        pass_through_election="ELECTED",
    )
    assertions.assert_risk_score(stored_interest, 70, "IN_SERVICE")
    assertions.assert_fields(
        get_success_data(
            api.get_compliance_covenant(covenant["id"], cast.developer_headers)
        ),
        "breached covenant",
        status="BREACHED",
    )
    stored_project = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(stored_project, compliance_status="CURE_PENDING")
    assertions.assert_ledger(stored_project, max_investor_risk_score=70)
    assertions.assert_fields(
        validate_success(api.get_credit_claim(claim["id"], headers)),
        "the unfiled claim",
        status="DRAFT",
        filed_at=None,
        gross_credit_cents=2_400_000,
        net_claim_cents=0,
    )
