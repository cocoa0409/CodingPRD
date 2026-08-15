"""Lien searches: result recording, hit classification, priority position, the
name-match rule (including DL safe harbor), and the parallel reflection dimension."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_search_result_hit,
    create_draft_attempt,
    create_ready_request,
    get_filing,
    get_search,
    order_lien_search,
    record_search_results,
    register_debtor,
    reject_attempt,
    set_clock_to,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_rerecord_results_rejected(api):
    """PRD §3.7: "The search must still be `ORDERED` (otherwise
    `ERR_SEARCH_NOT_ORDERED`)".

    Design: Corner/state_machines/rerecord_results_rejected
    """
    world = setup_client_world()
    search = order_lien_search(world["client"], world["debtor"])
    record_search_results(search["id"], "2026-08-01T00:00:00Z", [])
    resp = api.record_search_results(
        search["id"], {"through_date": "2026-08-01T00:00:00Z", "hits": []}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_SEARCH_NOT_ORDERED)
    assert get_search(search["id"])["status"] == "COMPLETED", (
        "the one-shot recording leaves the completed result set untouched"
    )


def test_pre_filing_prior_lien_count_exact_only(api):
    """PRD §3.7: "A `PRE_FILING` search moves `ORDERED` → `COMPLETED`, and its
    `prior_lien_count` is set to the number of `EXACT_MATCH` hits."
    PRD §3.7: "Only `EXACT_MATCH` hits count toward prior-lien totals and priority
    position."

    Design: Corner/calculations/pre_filing_prior_lien_count_exact_only
    """
    world = setup_client_world()
    search = order_lien_search(world["client"], world["debtor"])
    resolved = record_search_results(search["id"], "2026-08-01T00:00:00Z", [
        {"found_debtor_name": "Acme Manufacturing, Inc.",
         "found_filing_number": "CA-2020-001",
         "found_filed_at": "2020-01-15T00:00:00Z", "secured_party_name": "Bank A"},
        {"found_debtor_name": "ACME MANUFACTURING INC",
         "found_filing_number": "CA-2021-002",
         "found_filed_at": "2021-03-01T00:00:00Z", "secured_party_name": "Bank B"},
        {"found_debtor_name": "Acme Mfg Inc",
         "found_filing_number": "CA-2019-003",
         "found_filed_at": "2019-06-01T00:00:00Z", "secured_party_name": "Bank C"},
    ])
    assert resolved["status"] == "COMPLETED"
    assert resolved["prior_lien_count"] == 2, (
        f"only the two EXACT_MATCH spellings count, got {resolved['prior_lien_count']}"
    )


def test_priority_tie_break_by_filing_number(api):
    """PRD §3.7: "`priority_position_of_subject` is computed as one plus the number of
    competing hits — `EXACT_MATCH` hits that are not the subject — that precede the
    subject in filing order, where a competing hit precedes the subject when its
    `found_filed_at` is earlier than the subject's `filed_at`, or when the two
    datetimes are equal and its `found_filing_number` sorts lexicographically before
    the subject's `filing_number`".
    PRD §3.7: "Only `EXACT_MATCH` hits count toward prior-lien totals and priority
    position."

    Design: Corner/calculations/priority_tie_break_by_filing_number
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-100")
    search = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    resolved = record_search_results(search["id"], "2026-08-01T00:00:00Z", [
        # Strictly earlier by date: precedes.
        {"found_debtor_name": "Acme Manufacturing, Inc.",
         "found_filing_number": "2020-001",
         "found_filed_at": "2020-01-01T00:00:00Z", "secured_party_name": "Other Bank"},
        # Same filed_at, lexicographically smaller number: precedes.
        {"found_debtor_name": "ACME MANUFACTURING INC",
         "found_filing_number": "CA-2026-099",
         "found_filed_at": "2026-08-01T00:00:00Z", "secured_party_name": "Second Bank"},
        # The subject itself.
        {"found_debtor_name": "Acme Manufacturing, Inc.",
         "found_filing_number": "CA-2026-100",
         "found_filed_at": "2026-08-01T00:00:00Z", "secured_party_name": "Acme Lending"},
        # Earliest of all but only SIMILAR: excluded from the count.
        {"found_debtor_name": "Acme Mfg Inc",
         "found_filing_number": "2019-500",
         "found_filed_at": "2019-01-01T00:00:00Z", "secured_party_name": "Third Bank"},
    ])
    assert resolved["status"] == "VERIFIED"
    assert resolved["priority_position_of_subject"] == 3, (
        f"1 + 2 preceding EXACT_MATCH competitors, got "
        f"{resolved['priority_position_of_subject']}"
    )
    hits, _ = validate_paginated(api.list_search_hits(search["id"], ADMIN))
    similar = [h for h in hits if h["found_filing_number"] == "2019-500"]
    assert similar and similar[0]["hit_kind"] == "SIMILAR", (
        "the earliest-dated but merely similar hit is classified SIMILAR and excluded"
    )


def test_name_check_normalizes_punctuation_and_case(api):
    """PRD §3.4: "The name-match rule normalizes a name by uppercasing it, removing
    every character that is not an uppercase letter, a digit, or a space, collapsing
    each run of consecutive spaces into a single space, and trimming the ends."
    PRD §3.4: "A non-mutating name-check read evaluates the same rule on demand for
    any attempt and returns `match`, `normalized_submitted`, `normalized_of_record`,
    and `name_rule_applied`."

    Design: Corner/calculations/name_check_normalizes_punctuation_and_case
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(
        request["id"], debtor_name_on_filing="ACME MANUFACTURING INC")
    resp = api.name_check_filing(attempt["id"], SPECIALIST)
    data = validate_success(resp, expected_status=200)
    assert data["match"] is True
    assert data["normalized_submitted"] == "ACME MANUFACTURING INC"
    assert data["normalized_of_record"] == "ACME MANUFACTURING INC", (
        "punctuation and case are stripped from the name of record"
    )
    assert data["name_rule_applied"] == "LEGAL_NAME_ONLY"


def test_dl_safe_harbor_rule_tx_individual(api):
    """PRD §3.4: "The name of record is the debtor's `legal_name` for an
    `ORGANIZATION` debtor; for an `INDIVIDUAL` debtor it is the
    `drivers_license_name` in a jurisdiction whose `individual_name_rule` is
    `DL_SAFE_HARBOR` — and if the debtor has no `drivers_license_name` on record,
    submission fails with `ERR_DEBTOR_DL_NAME_MISSING` — or the `legal_name` in a
    `LEGAL_NAME_ONLY` jurisdiction. The normalized `debtor_name_on_filing` must equal
    the normalized name of record exactly; a mismatch is rejected with
    `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`."

    Design: Corner/calculations/dl_safe_harbor_rule_tx_individual
    """
    world = setup_client_world(profile_overrides={
        "state_code": "TX", "base_fee_cents": 8000,
        "per_additional_debtor_fee_cents": 1000, "county_surcharge_cents": 0,
        "county_filing_collateral_classes": [], "county_names": [],
        "individual_name_rule": "DL_SAFE_HARBOR", "expedited_daily_capacity": 1,
    })
    d1 = register_debtor(world["client"]["id"], debtor_type="INDIVIDUAL",
                         legal_name="John Q Public", jurisdiction_of_formation=None,
                         drivers_license_name="John Quincy Public")
    d2 = register_debtor(world["client"]["id"], debtor_type="INDIVIDUAL",
                         legal_name="Jane Roe", jurisdiction_of_formation=None)
    sp = world["secured_party"]
    # R1: the attempt carries the driver's-license name — passes in a DL state.
    r1 = create_ready_request(world["client"], d1, sp, jurisdiction_code="TX")
    f1 = create_draft_attempt(r1["id"], debtor_name_on_filing="John Quincy Public")
    # R2: the legal name is NOT the name of record under DL_SAFE_HARBOR.
    r2 = create_ready_request(world["client"], d1, sp, jurisdiction_code="TX")
    f2 = create_draft_attempt(r2["id"], debtor_name_on_filing="John Q Public")
    # R3: the debtor has no driver's-license name on record at all.
    r3 = create_ready_request(world["client"], d2, sp, jurisdiction_code="TX")
    f3 = create_draft_attempt(r3["id"], debtor_name_on_filing="Jane Roe")
    submitted = submit_attempt(f1["id"])
    assert submitted["effectiveness_status"] == "SUBMITTED"
    assert submitted["charged_fee_cents"] == 8000
    resp = api.submit_filing(f2["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING)
    resp = api.submit_filing(f3["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DEBTOR_DL_NAME_MISSING)


def test_through_date_too_early_for_verification(api):
    """PRD §3.7: "A verification search first requires that `through_date` be on or
    after the subject filing's `filed_at` (otherwise
    `ERR_SEARCH_THROUGH_DATE_TOO_EARLY`)."

    Design: Corner/validations/through_date_too_early_for_verification
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    search = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    resp = api.record_search_results(
        search["id"], {"through_date": "2026-07-31T00:00:00Z", "hits": []}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_SEARCH_THROUGH_DATE_TOO_EARLY)
    assert get_search(search["id"])["status"] == "ORDERED", (
        "the rejected recording leaves the search ORDERED"
    )
    assert get_filing(ctx["filing"]["id"])["reflection_status"] == "UNVERIFIED"


def test_search_hit_immutable_no_version_field(api):
    """PRD §2.5: "Search result hits, perfection reports, and filing events carry only
    `id` and `created_at`; both `updated_at` and `version` are absent on them, because
    hits and events are immutable records and each perfection report is a
    point-in-time snapshot that is never mutated after generation."
    PRD §3.7: "`hit_kind` is `EXACT_MATCH` when the normalized `found_debtor_name`
    equals the normalized debtor name of record under the name-match rule of §3.4, and
    `SIMILAR` otherwise".

    Design: Corner/entities/search_hit_immutable_no_version_field
    """
    world = setup_client_world()
    search = order_lien_search(world["client"], world["debtor"])
    record_search_results(search["id"], "2026-08-01T00:00:00Z", [{
        "found_debtor_name": "Acme Manufacturing, Inc.",
        "found_filing_number": "CA-2020-0001",
        "found_filed_at": "2020-01-15T00:00:00Z",
        "secured_party_name": "Other Bank",
    }])
    hits, meta = validate_paginated(api.list_search_hits(search["id"], ADMIN))
    assert meta["total_count"] == 1
    hit = hits[0]
    assert_search_result_hit(hit)
    assert hit["hit_kind"] == "EXACT_MATCH"


def test_discrepancy_search_does_not_change_effectiveness(api):
    """PRD §3.7: "When no subject hit is present, the search moves to `DISCREPANCY`,
    `priority_position_of_subject` stays null, and the subject's reflection moves from
    `UNVERIFIED` to `DISCREPANCY` with a `DISCREPANCY_FLAGGED` event".
    PRD §3.7: "Reflection and effectiveness are parallel dimensions on a filing:
    verification transitions never change `effectiveness_status`, and filing-office
    outcomes never change `reflection_status`, which evolves only through verification
    searches."

    Design: Difficulty/non_linear_state_machine/filing_parallel_effectiveness_and_reflection_dimensions
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    search = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    resolved = record_search_results(search["id"], "2026-08-01T00:00:00Z", [])
    assert resolved["status"] == "DISCREPANCY"
    assert resolved.get("priority_position_of_subject") is None
    filing = get_filing(ctx["filing"]["id"])
    assert filing["reflection_status"] == "DISCREPANCY"
    assert filing["effectiveness_status"] == "ACTIVE", (
        "a search outcome must never disturb the effectiveness dimension"
    )


def test_verified_search_flips_discrepancy_to_reflected(api):
    """PRD §3.7: "The subject filing's `reflection_status` then moves to `REFLECTED`
    — from `UNVERIFIED` or from `DISCREPANCY` — with a `REFLECTED` event appended to
    the subject."
    PRD §3.7: "with no preceding competitors the position is 1."

    Design: Difficulty/non_linear_state_machine/filing_parallel_effectiveness_and_reflection_dimensions
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    first = order_lien_search(ctx["client"], ctx["debtor"],
                              purpose="POST_FILING_VERIFICATION",
                              subject_filing_id=ctx["filing"]["id"])
    record_search_results(first["id"], "2026-08-01T00:00:00Z", [])
    assert get_filing(ctx["filing"]["id"])["reflection_status"] == "DISCREPANCY"
    second = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    resolved = record_search_results(second["id"], "2026-08-01T00:00:00Z", [{
        "found_debtor_name": "Acme Manufacturing, Inc.",
        "found_filing_number": "CA-2026-0001",
        "found_filed_at": "2026-08-01T00:00:00Z",
        "secured_party_name": "Acme Lending",
    }])
    assert resolved["status"] == "VERIFIED"
    assert resolved["priority_position_of_subject"] == 1
    filing = get_filing(ctx["filing"]["id"])
    assert filing["reflection_status"] == "REFLECTED", (
        "the second verification flips DISCREPANCY to REFLECTED"
    )
    assert filing["effectiveness_status"] == "ACTIVE"


def test_priority_position_empty_competing_set_is_one(api):
    """PRD §3.7: "with no preceding competitors the position is 1."
    PRD §3.7: "When a subject hit is present, the search moves to `VERIFIED` and
    `priority_position_of_subject` is computed as one plus the number of competing
    hits — `EXACT_MATCH` hits that are not the subject — that precede the subject in
    filing order".

    Design: Difficulty/boundary_precision_check/priority_position_empty_competing_set_is_one
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0100")
    search = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    resolved = record_search_results(search["id"], "2026-08-01T00:00:00Z", [{
        "found_debtor_name": "Acme Manufacturing, Inc.",
        "found_filing_number": "CA-2026-0100",
        "found_filed_at": "2026-08-01T00:00:00Z",
        "secured_party_name": "Acme Lending",
    }])
    assert resolved["status"] == "VERIFIED"
    assert resolved["priority_position_of_subject"] == 1, (
        "an empty competing set yields exactly position 1"
    )
    assert get_filing(ctx["filing"]["id"])["reflection_status"] == "REFLECTED"


def test_subject_hit_flagged_in_verification_search(api):
    """PRD §3.7: "`is_subject_filing` is true exactly when the search has a subject and
    the hit's `found_filing_number` equals the subject's `filing_number`."
    PRD §3.7: "`hit_kind` is `EXACT_MATCH` when the normalized `found_debtor_name`
    equals the normalized debtor name of record under the name-match rule of §3.4, and
    `SIMILAR` otherwise".

    Design: Difficulty/boundary_precision_check/priority_position_empty_competing_set_is_one
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0100")
    search = order_lien_search(ctx["client"], ctx["debtor"],
                               purpose="POST_FILING_VERIFICATION",
                               subject_filing_id=ctx["filing"]["id"])
    record_search_results(search["id"], "2026-08-01T00:00:00Z", [{
        "found_debtor_name": "Acme Manufacturing, Inc.",
        "found_filing_number": "CA-2026-0100",
        "found_filed_at": "2026-08-01T00:00:00Z",
        "secured_party_name": "Acme Lending",
    }])
    hits, meta = validate_paginated(api.list_search_hits(search["id"], ADMIN))
    assert meta["total_count"] == 1
    assert hits[0]["is_subject_filing"] is True, (
        "the hit carrying the subject's filing number is flagged as the subject"
    )
    assert hits[0]["hit_kind"] == "EXACT_MATCH"


def test_verification_search_on_rejected_subject_rejected(api):
    """PRD §3.7: "`subject_filing_id` is required exactly when the purpose is
    `POST_FILING_VERIFICATION`, and the subject filing must be `ACTIVE`, failing with
    `ERR_TARGET_FILING_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/verification_search_requires_subject_active
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    reject_attempt(attempt["id"], reason="MISSING_SIGNATURE")
    resp = api.create_lien_search(
        {
            "client_id": world["client"]["id"],
            "purpose": "POST_FILING_VERIFICATION",
            "debtor_id": world["debtor"]["id"],
            "jurisdiction_code": "CA",
            "subject_filing_id": attempt["id"],
        },
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_FILING_NOT_ACTIVE)
    assert get_filing(attempt["id"])["effectiveness_status"] == "REJECTED"


def test_verification_search_on_lapsed_subject_rejected(api):
    """PRD §3.7: "`subject_filing_id` is required exactly when the purpose is
    `POST_FILING_VERIFICATION`, and the subject filing must be `ACTIVE`, failing with
    `ERR_TARGET_FILING_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/verification_search_requires_subject_active
    """
    set_clock_to("2021-08-01T00:00:00Z")
    ctx = setup_active_initial_filing(filed_at="2021-08-01T00:00:00Z",
                                      filing_number="CA-2021-0001")
    # Expiration 2026-08-01T00:00:00Z; the sweep on this clock move lapses the filing.
    set_clock_to("2026-08-01T00:00:00Z")
    assert get_filing(ctx["filing"]["id"])["effectiveness_status"] == "LAPSED"
    resp = api.create_lien_search(
        {
            "client_id": ctx["client"]["id"],
            "purpose": "POST_FILING_VERIFICATION",
            "debtor_id": ctx["debtor"]["id"],
            "jurisdiction_code": "CA",
            "subject_filing_id": ctx["filing"]["id"],
        },
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_FILING_NOT_ACTIVE)
