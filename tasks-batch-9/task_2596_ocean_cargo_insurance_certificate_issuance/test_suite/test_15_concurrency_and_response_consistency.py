"""
Optimistic concurrency on the two parents that carry it, and the immediate
consistency of the objects the API hands back.

The first half issues certificates and lodges general average security against
stale and fresh parent versions, checking that a refused precondition leaves
every ledger exactly where it was. The second half checks that a successful
call returns everything it derived and that the movements it cascaded into
neighbouring rows are readable straight afterwards.
"""

from prd_bench_local_runner.testing import (
    assert_version_incremented,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers import (
    CLAIMS_ADJUSTER,
    ERR_STALE_GA_EVENT_VERSION,
    ERR_STALE_POLICY_VERSION,
    EXPECTED_BASE_PREMIUM,
    EXPECTED_EFFECTIVE_RATE,
    EXPECTED_GA_CONTRIBUTION_LARGEST,
    EXPECTED_GA_CONTRIBUTION_SMALLER,
    EXPECTED_GA_DEPOSIT_LARGEST,
    EXPECTED_GA_DEPOSIT_SMALLER,
    EXPECTED_GA_DEPOSIT_TOTAL,
    EXPECTED_INSURED_VALUE_CIF,
    EXPECTED_STRIKES_PREMIUM,
    EXPECTED_TOTAL_PREMIUM,
    EXPECTED_TRANSIT_TERMINATION,
    EXPECTED_WAR_PREMIUM,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    add_claim_document,
    assert_instant,
    assert_money,
    assert_rate,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    build_ga_event_with_security_calls,
    build_surveyor_environment,
    create_survey_order,
    ga_event_version,
    issue_certificate,
    make_assured_headers,
    open_claim_file,
    policy_version,
    post_ga_security,
    read_certificate,
    read_claim_file,
    read_ga_event,
    read_ga_posting,
    read_policy,
    read_surveyor,
    read_vessel,
)

# The voyage the canonical shipment sails: cover attaches at the sailing
# instant and lapses thirty free storage days after discharge.
EXPECTED_ATTACHMENT = "2026-08-10T00:00:00Z"

# Two shipments declared under one cover, so a version read before the first
# issue is stale by the time the second one is attempted.
DRAFT_A_NUMBER = "CERT-OCC-A"
DRAFT_B_NUMBER = "CERT-OCC-B"

# The attendance window a claims adjuster books: two whole hours.
SURVEY_WINDOW_START = "2026-09-08T09:00:00Z"
SURVEY_WINDOW_END = "2026-09-08T11:00:00Z"
SURVEY_WINDOW_MINUTES = 120

# The depreciation the adjuster already knows when the file is opened.
CLAIM_DAMAGE_PCT = 12.5

# The mandatory evidence, appended one document at a time.
MANDATORY_DOC_TYPES = ["SURVEY_REPORT", "BILL_OF_LADING", "CARRIER_CLAIM_LETTER"]


def _build_two_drafts_on_one_cover(api: ApiClient) -> JsonDict:
    """
    One active open cover carrying two declared but unissued shipments, each
    valuing at 1155000.00, plus the policy version observed before either of
    them was issued.
    """
    env = build_canonical_environment(api)
    env["draft_a"] = build_draft_certificate(
        api, env, certificate_number=DRAFT_A_NUMBER)
    env["draft_b"] = build_draft_certificate(
        api, env, certificate_number=DRAFT_B_NUMBER)
    env["observed_version"] = policy_version(api, env["policy_id"])
    return env


def _issue_and_capture(api: ApiClient, env: JsonDict, **overrides: object) -> JsonDict:
    """Declare one shipment and return the body the issue call itself returned."""
    draft = build_draft_certificate(api, env, **overrides)
    return validate_success(api.issue_certificate(
        draft["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER))


def test_issue_on_a_policy_version_another_issue_has_moved_is_refused(
        api: ApiClient) -> None:
    """
    A version read before the first certificate was issued no longer matches the
    cover, so the second issue is refused and books nothing.

    If that value does not equal the policy's current `version`, the issue is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412).

    Design: Corner/cross_cutting_complexity_layers/certificate_issue_on_a_stale_policy_version_returns_a_precondition_failure
    """
    env = _build_two_drafts_on_one_cover(api)
    stale_version = env["observed_version"]
    issue_certificate(api, env["draft_a"]["id"], env["policy_id"])

    validate_error(
        api.issue_certificate(
            env["draft_b"]["id"],
            {"expected_open_policy_version": stale_version},
            UNDERWRITER),
        ERR_STALE_POLICY_VERSION)

    refused = read_certificate(api, env["draft_b"]["id"])
    assert refused["status"] == "DRAFT"
    assert refused["effective_rate_per_mille"] is None
    assert refused["attachment_at"] is None
    assert refused["issued_at"] is None, (
        "a refused issue must not stamp the certificate"
    )

    policy = read_policy(api, env["policy_id"])
    assert_version_incremented(policy["version"], stale_version)
    assert policy["certificates_issued_count"] == 1, (
        "only the accepted issue may count against the cover"
    )
    assert_money(policy["aggregate_insured_value_booked"],
                 EXPECTED_INSURED_VALUE_CIF, "aggregate_insured_value_booked")
    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 EXPECTED_INSURED_VALUE_CIF, "vessel accumulated_insured_value")


def test_issue_succeeds_once_the_client_re_reads_the_policy_version(
        api: ApiClient) -> None:
    """
    Re-reading the cover after the refusal yields the version that lets the
    second shipment through, and both lines then sit on the ledgers.

    Issuing a certificate requires `expected_open_policy_version`, carrying the client's last observed `version` of the parent `OpenPolicy`.

    Design: Corner/cross_cutting_complexity_layers/certificate_issue_on_a_stale_policy_version_returns_a_precondition_failure
    """
    env = _build_two_drafts_on_one_cover(api)
    issue_certificate(api, env["draft_a"]["id"], env["policy_id"])
    validate_error(
        api.issue_certificate(
            env["draft_b"]["id"],
            {"expected_open_policy_version": env["observed_version"]},
            UNDERWRITER),
        ERR_STALE_POLICY_VERSION)

    fresh_version = policy_version(api, env["policy_id"])
    accepted = validate_success(api.issue_certificate(
        env["draft_b"]["id"],
        {"expected_open_policy_version": fresh_version},
        UNDERWRITER))
    assert accepted["status"] == "ISSUED"
    assert_money(accepted["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "insured_value of the second line")

    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 2
    assert_money(policy["aggregate_insured_value_booked"],
                 2 * EXPECTED_INSURED_VALUE_CIF,
                 "aggregate_insured_value_booked after both issues")
    assert_version_incremented(policy["version"], fresh_version)

    assert_money(read_vessel(api, env["vessel_id"])["accumulated_insured_value"],
                 2 * EXPECTED_INSURED_VALUE_CIF,
                 "vessel accumulated_insured_value after both issues")
    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"vessel_id": env["vessel_id"], "scope_type": "VESSEL",
                          "status": "ACTIVE"}),
        2, "active vessel-scoped ledger rows")


def test_security_posting_on_an_event_version_the_first_posting_moved_is_refused(
        api: ApiClient) -> None:
    """
    The second contributor posts against the event version it read before the
    first posting was accepted, and is refused without moving any ledger.

    If it does not equal the event's current `version`, the posting is rejected with `ERR_STALE_GA_EVENT_VERSION` (HTTP 412).

    Design: Corner/cross_cutting_complexity_layers/general_average_posting_on_a_stale_event_version_returns_a_precondition_failure
    """
    env = build_ga_event_with_security_calls(api)
    stale_version = ga_event_version(api, env["ga_event_id"])
    post_ga_security(api, env["posting_a_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_LARGEST, EXPECTED_GA_DEPOSIT_LARGEST,
                     ga_event_id=env["ga_event_id"])

    validate_error(
        api.post_ga_security(
            env["posting_d_id"],
            {"expected_ga_event_version": stale_version,
             "guarantee_amount": EXPECTED_GA_CONTRIBUTION_SMALLER,
             "cash_deposit_amount": EXPECTED_GA_DEPOSIT_SMALLER},
            make_assured_headers(env["policy_id"])),
        ERR_STALE_GA_EVENT_VERSION)

    refused = read_ga_posting(api, env["posting_d_id"], CLAIMS_ADJUSTER)
    assert refused["status"] == "REQUIRED", (
        "a refused posting stays outstanding"
    )
    assert_money(read_policy(api, env["policy_id"])["security_deposit_held_amount"],
                 EXPECTED_GA_DEPOSIT_LARGEST,
                 "security_deposit_held_amount after one accepted posting")

    event = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert event["status"] == "SECURITY_COLLECTING"
    assert event["postings_posted_count"] == 1, (
        "the refused posting must not be counted"
    )
    assert_version_incremented(event["version"], stale_version)


def test_security_posting_succeeds_on_a_freshly_read_event_version(
        api: ApiClient) -> None:
    """
    Re-reading the event lets the second contributor lodge 64450.40 with a cash
    deposit of 12890.08, taking the held deposits to 31500.00.

    On success the posting moves `REQUIRED → POSTED` with both amounts stored, the certificate's own policy has its `security_deposit_held_amount` increased by the cash deposit, and the event's `postings_posted_count` increments and its `version` increments.

    Design: Corner/cross_cutting_complexity_layers/general_average_posting_on_a_stale_event_version_returns_a_precondition_failure
    """
    env = build_ga_event_with_security_calls(api)
    stale_version = ga_event_version(api, env["ga_event_id"])
    post_ga_security(api, env["posting_a_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_LARGEST, EXPECTED_GA_DEPOSIT_LARGEST,
                     ga_event_id=env["ga_event_id"])
    validate_error(
        api.post_ga_security(
            env["posting_d_id"],
            {"expected_ga_event_version": stale_version,
             "guarantee_amount": EXPECTED_GA_CONTRIBUTION_SMALLER,
             "cash_deposit_amount": EXPECTED_GA_DEPOSIT_SMALLER},
            make_assured_headers(env["policy_id"])),
        ERR_STALE_GA_EVENT_VERSION)

    fresh_version = ga_event_version(api, env["ga_event_id"])
    accepted = validate_success(api.post_ga_security(
        env["posting_d_id"],
        {"expected_ga_event_version": fresh_version,
         "guarantee_amount": EXPECTED_GA_CONTRIBUTION_SMALLER,
         "cash_deposit_amount": EXPECTED_GA_DEPOSIT_SMALLER},
        make_assured_headers(env["policy_id"])))
    assert accepted["status"] == "POSTED"
    assert_money(accepted["guarantee_amount"], EXPECTED_GA_CONTRIBUTION_SMALLER,
                 "guarantee_amount")
    assert_money(accepted["cash_deposit_amount"], EXPECTED_GA_DEPOSIT_SMALLER,
                 "cash_deposit_amount")

    assert_money(read_policy(api, env["policy_id"])["security_deposit_held_amount"],
                 EXPECTED_GA_DEPOSIT_TOTAL,
                 "security_deposit_held_amount after both postings")
    assert_version_incremented(
        read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)["version"],
        fresh_version)


def test_the_posting_that_completes_the_call_closes_the_collection(
        api: ApiClient) -> None:
    """
    Lodging the last of the two called securities completes the collection in
    the very request that accepted it.

    When that counter reaches `postings_required_count` as a consequence of the posting just accepted, the event moves `SECURITY_COLLECTING → SECURITY_COMPLETE` in the same request.

    Design: Corner/cross_cutting_complexity_layers/general_average_posting_on_a_stale_event_version_returns_a_precondition_failure
    """
    env = build_ga_event_with_security_calls(api)
    post_ga_security(api, env["posting_a_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_LARGEST, EXPECTED_GA_DEPOSIT_LARGEST,
                     ga_event_id=env["ga_event_id"])
    halfway = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert halfway["status"] == "SECURITY_COLLECTING"

    post_ga_security(api, env["posting_d_id"], env["policy_id"],
                     EXPECTED_GA_CONTRIBUTION_SMALLER, EXPECTED_GA_DEPOSIT_SMALLER,
                     ga_event_id=env["ga_event_id"])

    completed = read_ga_event(api, env["ga_event_id"], CLAIMS_ADJUSTER)
    assert completed["status"] == "SECURITY_COMPLETE"
    assert completed["postings_posted_count"] == 2
    assert completed["postings_posted_count"] == completed["postings_required_count"]


def test_the_issue_response_carries_every_field_the_issue_derived(
        api: ApiClient) -> None:
    """
    The body returned by the issue call already holds the valuation, the rate,
    all four premium fields and both cover instants, and a later read repeats
    them unchanged.

    Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.

    Design: Corner/consistency_model/issue_response_already_carries_every_derived_field_it_wrote
    """
    env = build_canonical_environment(api)
    issued = _issue_and_capture(api, env)

    assert is_valid_uuid(issued["id"])
    assert issued["status"] == "ISSUED"
    assert is_iso8601_timestamp(issued["issued_at"])
    assert_money(issued["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "insured_value in the issue response")
    assert_rate(issued["effective_rate_per_mille"], EXPECTED_EFFECTIVE_RATE,
                label="effective_rate_per_mille in the issue response")
    assert_money(issued["base_premium_amount"], EXPECTED_BASE_PREMIUM,
                 "base_premium_amount in the issue response")
    assert_money(issued["war_premium_amount"], EXPECTED_WAR_PREMIUM,
                 "war_premium_amount in the issue response")
    assert_money(issued["strikes_premium_amount"], EXPECTED_STRIKES_PREMIUM,
                 "strikes_premium_amount in the issue response")
    assert_money(issued["total_premium_amount"], EXPECTED_TOTAL_PREMIUM,
                 "total_premium_amount in the issue response")
    assert_instant(issued["attachment_at"], EXPECTED_ATTACHMENT,
                   "attachment_at")
    assert_instant(issued["transit_termination_at"],
                   EXPECTED_TRANSIT_TERMINATION, "transit_termination_at")

    reread = read_certificate(api, issued["id"])
    for field in ("status", "insured_value", "effective_rate_per_mille",
                  "base_premium_amount", "war_premium_amount",
                  "strikes_premium_amount", "total_premium_amount",
                  "attachment_at", "transit_termination_at", "issued_at",
                  "version"):
        assert reread[field] == issued[field], (
            f"{field} differs between the issue response and a later read"
        )


def test_the_cover_ledgers_have_already_moved_when_the_issue_returns(
        api: ApiClient) -> None:
    """
    Reading the parent cover straight after the issue shows the insured value,
    the premium and the certificate count already booked.

    On the policy, `aggregate_insured_value_booked` rises by the insured value, `aggregate_premium_booked` rises by the total premium, and `certificates_issued_count` increments by one — that counter records every certificate that has ever left `DRAFT`, so it never falls back when one is later cancelled.

    Design: Corner/consistency_model/issue_response_already_carries_every_derived_field_it_wrote
    """
    env = build_canonical_environment(api)
    issued = _issue_and_capture(api, env)

    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"],
                 EXPECTED_INSURED_VALUE_CIF, "aggregate_insured_value_booked")
    assert_money(policy["aggregate_premium_booked"], EXPECTED_TOTAL_PREMIUM,
                 "aggregate_premium_booked")
    assert policy["certificates_issued_count"] == 1

    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": issued["id"], "status": "ACTIVE"}),
        3, "ledger rows written by the issue")


def test_opening_a_claim_moves_the_certificate_in_the_same_request(
        api: ApiClient) -> None:
    """
    The claim comes back opened with its two axes and three money fields at
    their initial values, and the certificate it names has already been claimed.

    Opening the claim creates the file in `status` `OPENED` with `subrogation_status` `NOT_STARTED`, `documentation_complete` false, `warranty_breach` false, `recovered_amount` 0.00 and `net_loss_amount` 0.00, and it moves the certificate `ISSUED → CLAIMED`.

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_response_of_the_call_that_triggered_them
    """
    env = build_environment_with_issued_certificate(api)

    claim = open_claim_file(api, env["certificate_id"],
                            damage_percentage=CLAIM_DAMAGE_PCT)
    assert claim["status"] == "OPENED"
    assert claim["subrogation_status"] == "NOT_STARTED"
    assert claim["documentation_complete"] is False
    assert claim["warranty_breach"] is False
    assert_money(claim["recovered_amount"], 0.00, "recovered_amount")
    assert_money(claim["net_loss_amount"], 0.00, "net_loss_amount")

    certificate = read_certificate(api, env["certificate_id"])
    assert certificate["status"] == "CLAIMED", (
        "the cascade onto the certificate must be readable at once"
    )
    assert_total_count(
        api.list_accumulation_entries(
            UNDERWRITER, {"certificate_id": env["certificate_id"],
                          "status": "ACTIVE"}),
        3, "ledger rows of a claimed certificate")


def test_appointing_a_surveyor_books_the_calendar_and_moves_the_claim(
        api: ApiClient) -> None:
    """
    A two-hour attendance window returns as 120 booked minutes, the surveyor's
    calendar carries them, and the claim has moved on.

    On success the order is created in `status` `APPOINTED`, its `window_minutes` is computed as the whole number of minutes between the two window instants, the surveyor's `booked_minutes_total` rises by that figure, and the claim moves to `SURVEY_ORDERED` — from `OPENED` on a first survey, or from `DOCS_INCOMPLETE` when the file is going round the rework loop for a further survey.

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_response_of_the_call_that_triggered_them
    """
    env = build_surveyor_environment(api)

    order = create_survey_order(api, env["claim_id"], env["surveyor_id"],
                                SURVEY_WINDOW_START, SURVEY_WINDOW_END)
    assert order["status"] == "APPOINTED"
    assert order["window_minutes"] == SURVEY_WINDOW_MINUTES, (
        "two whole hours are 120 minutes"
    )

    surveyor = read_surveyor(api, env["surveyor_id"], CLAIMS_ADJUSTER)
    assert surveyor["booked_minutes_total"] == SURVEY_WINDOW_MINUTES
    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "SURVEY_ORDERED", (
        "the appointment must have moved the claim in the same request"
    )


def test_the_third_mandatory_document_completes_the_evidence_log(
        api: ApiClient) -> None:
    """
    Documentation stays incomplete after the survey report and the bill of
    lading, and becomes complete the moment the carrier claim letter is added.

    Appending a document re-derives the claim's `documentation_complete`, which becomes true once the log holds at least one document of each of the three mandatory types `SURVEY_REPORT`, `BILL_OF_LADING` and `CARRIER_CLAIM_LETTER`; `COMMERCIAL_INVOICE`, `PACKING_LIST` and `PHOTO_SET` are useful but optional evidence.

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_response_of_the_call_that_triggered_them
    """
    env = build_environment_with_issued_certificate(api)
    claim = open_claim_file(api, env["certificate_id"],
                            damage_percentage=CLAIM_DAMAGE_PCT)
    claim_id = claim["id"]

    completeness = []
    for index, doc_type in enumerate(MANDATORY_DOC_TYPES, start=1):
        add_claim_document(api, claim_id, doc_type, f"EVIDENCE-{index}")
        completeness.append(
            read_claim_file(api, claim_id, CLAIMS_ADJUSTER)["documentation_complete"])

    assert completeness == [False, False, True], (
        "the log completes only once all three mandatory types are present, "
        f"got {completeness}"
    )
