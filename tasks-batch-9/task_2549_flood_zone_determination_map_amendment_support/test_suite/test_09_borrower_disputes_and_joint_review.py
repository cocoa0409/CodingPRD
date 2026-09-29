"""Borrower disputes: admissibility, the two-stage joint review, and its outcomes.

A dispute is filed by the one borrower named on the folio, is admissible only on
grounds the evidence supports, and is then decided by two different people in
sequence.  A denial hands the original determination back untouched; a sustain
rewrites the building's geometry and cascades all the way out to the notice.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    AGENCY_USER_ID,
    ANALYST_USER_ID,
    REVIEWER_USER_ID,
    ApiErrorId,
    agency_review_dispute,
    api_client,
    assert_dispute,
    create_dispute_payload,
    file_dispute,
    make_agency_headers,
    make_analyst_headers,
    make_borrower_headers,
    make_reviewer_headers,
    provider_review_dispute,
    read_folio,
    setup_base_chain,
    setup_dispute_in_joint_review,
    setup_dispute_submitted,
    setup_folio_with_mandatory_notice,
)

CLOCK = "2026-08-01T00:00:00Z"
DECISION_DUE = "2026-08-31T00:00:00Z"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 fixes the wire format at three fractional digits, so an instant the
    test supplied as ``...T00:00:00Z`` is read back as ``...T00:00:00.000Z``.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def disputes_for(determination_id):
    return validate_paginated(
        api_client.list_disputes(
            headers=make_analyst_headers(),
            params={"determination_id": determination_id},
        )
    )


def read_determination(determination_id):
    return validate_success(
        api_client.get_determination(determination_id, headers=make_analyst_headers())
    )


def read_structure(structure_id):
    return validate_success(
        api_client.get_structure(structure_id, headers=make_analyst_headers())
    )


def test_a_freshly_filed_dispute_is_submitted_and_locks_the_determination():
    """Filing records the borrower's asserted offset on the dispute and nowhere else:
    the structure keeps the geometry it was digitised with, while the determination
    is taken out of the governing position for the duration of the review.

    PRD §3.9: "An admissible filing is created in `status` `SUBMITTED` with `round_number` 1, `filed_at` at the current logical instant, and `decision_due_at` computed as 30 days after `filed_at`; `provider_recommendation`, `provider_reviewed_by_user_id`, `agency_concurrence`, `agency_reviewed_by_user_id`, `resolution`, `revised_determination_id` and `resolved_at` all start null."
    PRD §3.9: "The challenged determination simultaneously moves `ISSUED → UNDER_DISPUTE`, which locks it for the duration of the joint review, and the folio's `compliance_posture` is recomputed — force placement is blocked while the review is open."
    PRD §3.9: "The filing names the `determination_id` under challenge, a `basis`, a `borrower_statement` giving the narrative, and an `asserted_sfha_offset_ft` — the signed boundary offset in feet the borrower claims is the correct one, which is the number that will be written onto the structure if the dispute succeeds."

    Design: Corner/state_machines/corner_dispute_created_in_initial_state_submitted
    """
    chain = setup_base_chain(clock=CLOCK)
    determination = chain["determination"]

    dispute = validate_success(
        api_client.create_dispute(
            create_dispute_payload(determination["id"], asserted_sfha_offset_ft=30.0),
            headers=make_borrower_headers(chain["folio"]["borrower_user_id"]),
        ),
        201,
    )
    assert_dispute(dispute)

    assert dispute["status"] == "SUBMITTED", "a filed dispute starts in SUBMITTED"
    assert dispute["round_number"] == 1
    for field in (
        "provider_recommendation",
        "provider_reviewed_by_user_id",
        "agency_concurrence",
        "agency_reviewed_by_user_id",
        "resolution",
        "revised_determination_id",
        "resolved_at",
    ):
        assert dispute[field] is None, f"{field} must start null on a fresh dispute"
    assert_instant(dispute["filed_at"], CLOCK)
    assert_instant(dispute["decision_due_at"], DECISION_DUE)
    assert dispute["asserted_sfha_offset_ft"] == 30.0

    locked = read_determination(determination["id"])
    assert locked["status"] == "UNDER_DISPUTE", (
        "the challenged determination moves ISSUED -> UNDER_DISPUTE in the same action"
    )

    structure = read_structure(chain["structure"]["id"])
    assert structure["sfha_offset_ft"] == -12.0, (
        "the asserted offset is only written onto the structure if the dispute succeeds"
    )


def test_a_borrower_who_is_not_named_on_the_folio_cannot_file_at_all():
    """Presence on the loan is checked before the grounds are ever weighed, so a
    stranger's filing is refused for who they are and not for what they claimed —
    and it leaves no dispute row behind for the real borrower to trip over.

    PRD §3.9: "Only a `Borrower` may file, and only against the folio they are named on; a filer whose `X-User-ID` does not equal the folio's `borrower_user_id` is rejected with `ERR_BORROWER_NOT_ON_LOAN`."
    PRD §2.5: "Seventh (7) a `Lender` caller's ownership of the target folio is checked, reporting `ERR_FOLIO_NOT_OWNED`; and eighth (8) a `Borrower` caller's presence on the target folio is checked, reporting `ERR_BORROWER_NOT_ON_LOAN`."
    PRD §2.5: "Requests are checked against a single ordered ladder, and the ladder is evaluated strictly from the lowest priority number upward."

    Design: Corner/errors/corner_borrower_not_on_the_loan_cannot_file_a_dispute
    """
    chain = setup_base_chain(clock=CLOCK)
    determination = chain["determination"]
    assert chain["folio"]["borrower_user_id"] == "borrower-a"
    stranger = make_borrower_headers("borrower-zz")

    validate_error(
        api_client.create_dispute(
            create_dispute_payload(determination["id"]), headers=stranger
        ),
        ApiErrorId.ERR_BORROWER_NOT_ON_LOAN,
        403,
    )

    validate_error(
        api_client.create_dispute(
            create_dispute_payload(determination["id"], basis="GEOCODE_ERROR"),
            headers=stranger,
        ),
        ApiErrorId.ERR_BORROWER_NOT_ON_LOAN,
        403,
    )

    assert read_determination(determination["id"])["status"] == "ISSUED", (
        "a refused filing does not lock the determination"
    )
    _, meta = disputes_for(determination["id"])
    assert meta["total_count"] == 0, "a refused filing writes no dispute row"

    accepted = validate_success(
        api_client.create_dispute(
            create_dispute_payload(determination["id"]),
            headers=make_borrower_headers("borrower-a"),
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE"
    _, meta = disputes_for(determination["id"])
    assert meta["total_count"] == 1


def test_the_same_grievance_is_inadmissible_on_three_grounds_and_admissible_on_a_fourth():
    """Admissibility is evidentiary and per-basis.  On a rooftop-geocoded property with
    no survey on file and no revision in flight, three of the four bases have nothing
    to stand on, while the fourth needs no evidence at all — same statement, same
    determination, four different answers.

    PRD §3.9: "Each `basis` carries its own admissibility precondition, and all four failures report `ERR_DISPUTE_BASIS_UNSUPPORTED` (HTTP 422)."
    PRD §3.9: "A `basis` of `GEOCODE_ERROR` requires that the property's `geocode_method` be something other than `ROOFTOP`, since a rooftop hit is the best positional evidence the geocoder can produce."
    PRD §3.9: "A `basis` of `ELEVATION_ABOVE_BFE` requires that the structure already have a `VALIDATED` elevation certificate on file."
    PRD §3.9: "A `basis` of `MAP_PANEL_STALE` requires that a later-sequence panel that is not yet `EFFECTIVE` actually exist for that map timeline — you cannot claim the map is out of date when no revision is in flight."
    PRD §3.9: "A `basis` of `STRUCTURE_LOCATION` carries no additional evidentiary precondition of its own."

    Design: Corner/validations/corner_geocode_error_dispute_basis_rejected_for_rooftop_property
    """
    chain = setup_base_chain(clock=CLOCK)
    determination = chain["determination"]
    assert chain["property"]["geocode_method"] == "ROOFTOP"
    borrower = make_borrower_headers(chain["folio"]["borrower_user_id"])

    for basis in ("GEOCODE_ERROR", "ELEVATION_ABOVE_BFE", "MAP_PANEL_STALE"):
        validate_error(
            api_client.create_dispute(
                create_dispute_payload(determination["id"], basis=basis),
                headers=borrower,
            ),
            ApiErrorId.ERR_DISPUTE_BASIS_UNSUPPORTED,
            422,
        )
        assert read_determination(determination["id"])["status"] == "ISSUED", (
            f"an inadmissible {basis} filing leaves the determination governing"
        )

    _, meta = disputes_for(determination["id"])
    assert meta["total_count"] == 0, "inadmissible filings leave no rows"

    dispute = validate_success(
        api_client.create_dispute(
            create_dispute_payload(determination["id"], basis="STRUCTURE_LOCATION"),
            headers=borrower,
        ),
        201,
    )
    assert dispute["basis"] == "STRUCTURE_LOCATION"
    assert dispute["status"] == "SUBMITTED"
    assert dispute["round_number"] == 1
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE"
    _, meta = disputes_for(determination["id"])
    assert meta["total_count"] == 1, "only the admissible filing became a row"


def test_the_provider_stage_records_a_position_and_only_then_opens_the_agency_stage():
    """The two review stages are strictly ordered and each excludes a different person:
    the provider stage is closed to whoever issued the determination, and once a
    reviewer has recorded a recommendation the agency stage is closed to them in turn.
    The provider stage records; it does not decide.

    PRD §3.9: "A `ProviderReviewer` then forms the provider's position on a dispute that is in `SUBMITTED`, supplying a `provider_recommendation` of `UPHOLD` (the determination stands) or `REVISE` (the borrower is right)."
    PRD §3.9: "The acting `X-User-ID` must differ from the `issued_by_user_id` recorded on the disputed determination, or the review is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The recommendation is stored, `provider_reviewed_by_user_id` records the acting `X-User-ID`, and the dispute moves `SUBMITTED → JOINT_AGENCY_REVIEW`."
    PRD §3.9: "An `AgencyOfficer` closes the joint review on a dispute that is in `JOINT_AGENCY_REVIEW` and whose `provider_recommendation` is not null, supplying an `agency_concurrence` of `CONCUR` or `NON_CONCUR`; the acting `X-User-ID` must differ from the dispute's current `provider_reviewed_by_user_id`."
    PRD §3.9: "Calling it on a dispute that is not in `JOINT_AGENCY_REVIEW` — including a second call against a dispute already `SUSTAINED` or `DENIED` — is rejected with `ERR_INVALID_DISPUTE_STATE`."

    Design: Corner/endpoints/corner_dispute_provider_review_records_recommendation_and_opens_agency_stage
    """
    chain = setup_dispute_submitted(clock=CLOCK)
    dispute_id = chain["dispute"]["id"]
    determination = chain["determination"]
    assert determination["issued_by_user_id"] == ANALYST_USER_ID

    validate_error(
        api_client.agency_review_dispute(
            dispute_id, {"agency_concurrence": "CONCUR"}, headers=make_agency_headers()
        ),
        ApiErrorId.ERR_INVALID_DISPUTE_STATE,
        409,
    )

    validate_error(
        api_client.provider_review_dispute(
            dispute_id,
            {"provider_recommendation": "REVISE"},
            headers=make_reviewer_headers(ANALYST_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE"

    reviewed = validate_success(
        api_client.provider_review_dispute(
            dispute_id,
            {"provider_recommendation": "REVISE"},
            headers=make_reviewer_headers(REVIEWER_USER_ID),
        )
    )
    assert_dispute(reviewed)
    assert reviewed["status"] == "JOINT_AGENCY_REVIEW"
    assert reviewed["provider_recommendation"] == "REVISE"
    assert reviewed["provider_reviewed_by_user_id"] == REVIEWER_USER_ID
    assert reviewed["agency_concurrence"] is None, (
        "the provider stage records a recommendation, it does not decide"
    )
    assert reviewed["agency_reviewed_by_user_id"] is None
    assert reviewed["resolution"] is None
    assert reviewed["resolved_at"] is None
    assert reviewed["round_number"] == 1

    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE", (
        "the determination stays locked across the provider stage"
    )
    folio = read_folio(chain["folio"]["id"])
    assert folio["required_coverage_cents"] == chain["folio"]["required_coverage_cents"], (
        "neither review stage touches the folio's obligation"
    )

    validate_error(
        api_client.agency_review_dispute(
            dispute_id,
            {"agency_concurrence": "CONCUR"},
            headers=make_agency_headers(REVIEWER_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )


def test_the_agency_stage_excludes_the_provider_reviewer_and_not_the_issuing_analyst():
    """The segregation anchor moves between the two stages.  At the agency stage it is
    the dispute's own ``provider_reviewed_by_user_id``, so the reviewer who just formed
    the recommendation is locked out while the analyst who originally issued the
    determination is not — and the lock-out is an identity refusal, not a role refusal.

    PRD §3.9: "An `AgencyOfficer` closes the joint review on a dispute that is in `JOINT_AGENCY_REVIEW` and whose `provider_recommendation` is not null, supplying an `agency_concurrence` of `CONCUR` or `NON_CONCUR`; the acting `X-User-ID` must differ from the dispute's current `provider_reviewed_by_user_id`."
    PRD §2.5: "Third (3) the caller's role must appear in the target endpoint's authorised role list, reporting `ERR_FORBIDDEN_ROLE`."
    PRD §3.9: "The dispute is **sustained** — `JOINT_AGENCY_REVIEW → SUSTAINED` — either when the agency concurs with a `REVISE` recommendation, in which case `resolution` is `REVISED_BY_CONCURRENCE`, or when the agency does not concur with an `UPHOLD` recommendation in the final round, in which case the agency has overridden the provider and `resolution` is `REVISED_BY_AGENCY_OVERRIDE`."
    PRD §3.9: "Both terminal outcomes set `resolved_at` to the current logical instant."
    PRD §3.9: "In the third hop, because the geometry changed, the disputed determination moves `UNDER_DISPUTE → SUPERSEDED` with `superseded_at` at the current logical instant and a replacement determination is minted with `determination_type` `DISPUTE_REVISION`, `supersedes_determination_id` naming the disputed row, `issued_by_user_id` set to the literal string `system`, and its geometry recomputed from the corrected offset under the strict variant of Section 3.5; the dispute's `revised_determination_id` names that new determination."

    Design: Corner/rbac/corner_dispute_agency_review_cannot_be_acted_by_the_provider_reviewer
    """
    chain = setup_dispute_in_joint_review(provider_recommendation="REVISE", clock=CLOCK)
    dispute_id = chain["dispute"]["id"]
    determination = chain["determination"]
    assert chain["dispute"]["provider_reviewed_by_user_id"] == REVIEWER_USER_ID
    assert determination["issued_by_user_id"] == ANALYST_USER_ID

    error = validate_error(
        api_client.agency_review_dispute(
            dispute_id,
            {"agency_concurrence": "CONCUR"},
            headers=make_agency_headers(REVIEWER_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert error["error_id"] != "ERR_FORBIDDEN_ROLE", (
        "the AgencyOfficer role is authorised here; only the identity is wrong"
    )

    unmoved = validate_success(
        api_client.get_dispute(dispute_id, headers=make_analyst_headers())
    )
    assert unmoved["status"] == "JOINT_AGENCY_REVIEW"
    assert unmoved["agency_concurrence"] is None
    assert unmoved["agency_reviewed_by_user_id"] is None
    assert unmoved["resolution"] is None
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE"

    decided = validate_success(
        api_client.agency_review_dispute(
            dispute_id,
            {"agency_concurrence": "CONCUR"},
            headers=make_agency_headers(ANALYST_USER_ID),
        )
    )
    assert_dispute(decided)
    assert decided["status"] == "SUSTAINED", (
        "the determination's issuer is not excluded from the agency stage"
    )
    assert decided["agency_concurrence"] == "CONCUR"
    assert decided["agency_reviewed_by_user_id"] == ANALYST_USER_ID
    assert decided["resolution"] == "REVISED_BY_CONCURRENCE"
    assert_instant(decided["resolved_at"], CLOCK)

    revised_id = decided["revised_determination_id"]
    assert revised_id is not None, "a sustain mints the replacement determination"
    revised = read_determination(revised_id)
    assert revised["supersedes_determination_id"] == determination["id"]
    _, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(),
            params={"loan_folio_id": chain["folio"]["id"]},
        )
    )
    assert meta["total_count"] == 2, "the sustain cascade minted exactly one revision"


def test_a_remand_recycles_the_dispute_and_the_denial_hands_the_determination_back():
    """The dispute state machine is cyclic: a first-round NON_CONCUR sends it back to
    SUBMITTED with the provider's fields wiped and the clock restarted, and the same
    NON_CONCUR in round 2 could no longer remand.  When the second round finally
    concurs with UPHOLD the original determination resumes governing, unrevised.

    PRD §3.9: "The third outcome is a **remand**: when the agency returns `NON_CONCUR` while `round_number` is still below the maximum of 2, the dispute cycles `JOINT_AGENCY_REVIEW → SUBMITTED` for a second provider review."
    PRD §3.9: "On a remand `round_number` is incremented by 1, `provider_recommendation` and `provider_reviewed_by_user_id` are both cleared to null so a fresh provider review is required, `agency_concurrence` is recorded as `NON_CONCUR` with `agency_reviewed_by_user_id` set, `filed_at` is reset to the current logical instant and `decision_due_at` is recomputed as 30 days after the new `filed_at`, and the disputed determination stays `UNDER_DISPUTE` throughout."
    PRD §3.9: "The dispute is **denied** — `JOINT_AGENCY_REVIEW → DENIED` — either when the agency concurs with an `UPHOLD` recommendation, giving `resolution` `UPHELD_BY_CONCURRENCE`, or when the agency does not concur with a `REVISE` recommendation in the final round, giving `resolution` `UPHELD_BY_AGENCY_OVERRIDE`."
    PRD §3.9: "Both terminal outcomes set `resolved_at` to the current logical instant."
    PRD §3.9: "The disputed determination returns `UNDER_DISPUTE → ISSUED` and nothing else about it changes — no field other than its `status`, `updated_at` and `version` is written, so the same row resumes the governing position."
    PRD §3.9: "No new determination is created and the structure's `sfha_offset_ft` is left untouched."

    Design: Difficulty/non_linear_state_machine/dispute_remand_cycle_returns_determination_to_issued
    """
    chain = setup_dispute_submitted(clock=CLOCK)
    dispute_id = chain["dispute"]["id"]
    determination = chain["determination"]

    assert chain["dispute"]["status"] == "SUBMITTED"
    assert chain["dispute"]["round_number"] == 1
    assert_instant(chain["dispute"]["decision_due_at"], DECISION_DUE)
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE"

    first_review = provider_review_dispute(dispute_id, "UPHOLD")
    assert first_review["status"] == "JOINT_AGENCY_REVIEW"

    remanded = agency_review_dispute(dispute_id, "NON_CONCUR")
    assert_dispute(remanded)
    assert remanded["status"] == "SUBMITTED", (
        "a NON_CONCUR below the round ceiling cycles the dispute back for a second review"
    )
    assert remanded["round_number"] == 2
    assert remanded["provider_recommendation"] is None, (
        "the remand clears the provider's position so a fresh review is required"
    )
    assert remanded["provider_reviewed_by_user_id"] is None
    assert remanded["agency_concurrence"] == "NON_CONCUR"
    assert remanded["agency_reviewed_by_user_id"] == AGENCY_USER_ID
    assert_instant(remanded["filed_at"], CLOCK)
    assert_instant(remanded["decision_due_at"], DECISION_DUE)
    assert remanded["resolution"] is None
    assert remanded["resolved_at"] is None
    assert read_determination(determination["id"])["status"] == "UNDER_DISPUTE", (
        "the remand does not move the determination"
    )

    second_review = provider_review_dispute(dispute_id, "UPHOLD")
    assert second_review["status"] == "JOINT_AGENCY_REVIEW"
    assert second_review["round_number"] == 2

    denied = agency_review_dispute(dispute_id, "CONCUR")
    assert denied["status"] == "DENIED"
    assert denied["resolution"] == "UPHELD_BY_CONCURRENCE"
    assert_instant(denied["resolved_at"], CLOCK)
    assert denied["revised_determination_id"] is None
    assert denied["round_number"] == 2

    restored = read_determination(determination["id"])
    assert restored["status"] == "ISSUED", "a denial returns the same row to ISSUED"
    assert restored["superseded_at"] is None
    assert restored["zone_code"] == determination["zone_code"]
    assert restored["sfha_flag"] == determination["sfha_flag"]

    assert read_structure(chain["structure"]["id"])["sfha_offset_ft"] == -12.0, (
        "a denial mutates no geometry"
    )
    _, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(),
            params={"loan_folio_id": chain["folio"]["id"]},
        )
    )
    assert meta["total_count"] == 1, "no revision was minted on the denial branch"


def test_sustaining_a_dispute_cascades_from_the_geometry_out_to_the_notice():
    """A sustain is the one action that rewrites a building's digitised geometry, and
    the rewrite propagates in order: structure, then a replacement determination that
    reclassifies the building as outside the hazard area, then the folio's obligation
    collapsing to zero, then the mandatory-purchase notice being superseded and a
    system re-determination notice taking its place.  No premium was ever placed here,
    so the escrow is a bystander.

    PRD §3.9: "In the first hop the dispute itself moves to `SUSTAINED` with `resolved_at` set."
    PRD §3.9: "In the second hop, because the borrower's assertion has been accepted, the disputed structure's `sfha_offset_ft` is overwritten with the dispute's `asserted_sfha_offset_ft` — this is the only path in the system that rewrites a structure's geometry."
    PRD §3.9: "In the third hop, because the geometry changed, the disputed determination moves `UNDER_DISPUTE → SUPERSEDED` with `superseded_at` at the current logical instant and a replacement determination is minted with `determination_type` `DISPUTE_REVISION`, `supersedes_determination_id` naming the disputed row, `issued_by_user_id` set to the literal string `system`, and its geometry recomputed from the corrected offset under the strict variant of Section 3.5; the dispute's `revised_determination_id` names that new determination."
    PRD §3.9: "In the fourth hop, because the folio's governing determination changed, the folio's `current_determination_id` is repointed and `required_coverage_cents`, `uninsured_exposure_cents` and `insurance_status` are recomputed; when the revision yields `sfha_flag` false and the folio's `insurance_status` was `FORCE_PLACED`, the coverage dimension moves `FORCE_PLACED → NOT_REQUIRED` and the escrow settlement of Section 3.6 refunds the unearned premium into `escrow_balance_cents`."
    PRD §3.9: "In the fifth hop, because the obligation has been cleared, every compliance notice on the folio whose `status` is `SENT` moves `SENT → SUPERSEDED` with `closed_at` set, `open_notice_count` is re-counted, `compliance_posture` is recomputed, and a system notice with `notice_type` `RE_DETERMINATION` citing the new determination is sent to the lender so the servicing file records why the obligation went away."
    PRD §3.5: "An `OUTSIDE` classification sets `zone_code` to `X` and `sfha_flag` false — `X` is a determination-only zone value that no panel ever carries, so the determination's `zone_code` ranges over `A`, `AE`, `AO`, `AH`, `VE` and `X`."
    PRD §3.5: "The determination's `base_flood_elevation_ft` is a snapshot of the governing panel's `base_flood_elevation_ft` when `sfha_flag` is true, and null when `sfha_flag` is false."
    PRD §3.5: "A folio whose `insurance_status` is `NONE` moves `NONE → NOT_REQUIRED` when the incoming current determination has `mandatory_purchase_flag` false; that transition sets `required_coverage_cents` to 0, sets `uninsured_exposure_cents` to 0, and recomputes `compliance_posture` to `COMPLIANT`."
    PRD §2.10: "`open_notice_count` on a folio is defined as the number of compliance notices on that folio whose `status` is `SENT`, counted across every notice type and with no time window applied, and it is recomputed by full re-count after every notice creation and after every notice transition out of `SENT`."

    Design: Difficulty/transitive_cascade/dispute_sustained_five_hop_cascade_to_not_required
    """
    chain = setup_folio_with_mandatory_notice(clock=CLOCK)
    determination = chain["determination"]
    notice = chain["notice"]
    folio_before = chain["folio"]
    assert folio_before["insurance_status"] == "NONE"
    assert folio_before["escrow_balance_cents"] == 500000
    assert notice["notice_type"] == "MANDATORY_PURCHASE"
    assert notice["status"] == "SENT"

    dispute = file_dispute(
        determination["id"], folio_before["borrower_user_id"],
        asserted_sfha_offset_ft=30.0,
    )
    provider_review_dispute(dispute["id"], "REVISE")
    sustained = agency_review_dispute(dispute["id"], "CONCUR")

    # Hop 1 — the dispute resolves.
    assert sustained["status"] == "SUSTAINED"
    assert sustained["resolution"] == "REVISED_BY_CONCURRENCE"
    assert_instant(sustained["resolved_at"], CLOCK)

    # Hop 2 — the geometry is rewritten.
    assert read_structure(chain["structure"]["id"])["sfha_offset_ft"] == 30.0, (
        "the accepted assertion replaces the digitised offset of -12.0"
    )

    # Hop 3 — the determination is replaced.
    revised_id = sustained["revised_determination_id"]
    assert revised_id is not None
    revised = read_determination(revised_id)
    assert revised["determination_type"] == "DISPUTE_REVISION"
    assert revised["supersedes_determination_id"] == determination["id"]
    assert revised["issued_by_user_id"] == "system"
    assert revised["position_class"] == "OUTSIDE"
    assert revised["sfha_flag"] is False
    assert revised["zone_code"] == "X"
    assert revised["base_flood_elevation_ft"] is None
    assert revised["mandatory_purchase_flag"] is False
    assert revised["status"] == "ISSUED"

    retired = read_determination(determination["id"])
    assert retired["status"] == "SUPERSEDED"
    assert_instant(retired["superseded_at"], CLOCK)

    # Hop 4 — the folio's obligation collapses.
    folio = read_folio(folio_before["id"])
    assert folio["current_determination_id"] == revised_id
    assert folio["insurance_status"] == "NOT_REQUIRED"
    assert folio["required_coverage_cents"] == 0
    assert folio["uninsured_exposure_cents"] == 0

    # Hop 5 — the notice set is closed out and the lender is told why.
    superseded_notice = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert superseded_notice["status"] == "SUPERSEDED"
    assert_instant(superseded_notice["closed_at"], CLOCK)

    notices, _ = validate_paginated(
        api_client.list_compliance_notices(
            headers=make_analyst_headers(), params={"loan_folio_id": folio_before["id"]}
        )
    )
    system_notices = [n for n in notices if n["notice_type"] == "RE_DETERMINATION"]
    assert len(system_notices) == 1, "the cascade sends exactly one re-determination notice"
    assert system_notices[0]["status"] == "SENT"
    assert system_notices[0]["determination_id"] == revised_id
    assert folio["open_notice_count"] == 1, (
        "the superseded notice left SENT and the system notice entered it"
    )
    assert folio["compliance_posture"] == "COMPLIANT"

    # The escrow is untouched: nothing was ever force placed on this folio.
    assert folio["escrow_balance_cents"] == 500000
    assert folio["cumulative_earned_premium_cents"] == 0
