"""Entity shapes at creation: declared defaults, ignored inputs, listings and lookups."""
from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    build_paired_loop_chain,
    create_program,
    create_recipient,
    setup_paired_loop_participants,
    setup_program_with_staff,
    set_clock,
    update_recipient_status,
    validate_chain,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_program_admin_headers


def _recipient_count(env):
    _rows, meta = validate_paginated(
        api_client.list_recipient_candidates(
            env["coordinator_headers"], params={"program_id": env["program_id"]}
        )
    )
    return meta["total_count"]


def test_program_creation_applies_every_declared_default():
    """PRD §3.1: "Eight further inputs are optional and each has a default, so a center
    can accept the house policy and adjust later: `organ_type` selects which organ
    program the center runs and is either `KIDNEY` or `LIVER`, defaulting to `KIDNEY`;
    `cooling_off_days` is the mandatory number of days a donor must be left between a
    consent disclosure and the advocate's attestation and defaults to 7, and it must be
    at least 1; `follow_up_completeness_threshold_pct` is the per-submission
    completeness percentage at or above which a follow-up interval counts as met and
    defaults to 80; `follow_up_compliance_threshold_pct` is the program-wide follow-up
    percentage below which the posture degrades and defaults to 75; both percentages
    must be greater than 0 and at most 100."
    PRD §3.1: "`expected_one_year_survival_rate` is the expected one-year graft
    survival rate that outcome reviews measure against, defaults to 0.95, and must be
    greater than 0 and at most 1."
    PRD §3.1: "Registration also fixes the program's starting derived state:
    `compliance_posture` begins at `OPEN`, `follow_up_compliance_pct` begins at 100
    because no follow-up interval is due yet, `cit_breach_count` begins at 0,
    `donor_fund_committed_cents` begins at 0 and `donor_fund_remaining_cents` begins
    equal to `donor_fund_pool_cents`."
    PRD §3.1: "The `last_sweep_at` field is null until the first compliance sweep
    runs."

    Design: Corner/entities/program_creation_applies_every_declared_default
    """
    set_clock(CLOCK_EPOCH)

    program = validate_success(
        api_client.create_program(
            {"name": "Default Policy Center", "center_code": "DEF-01"},
            make_program_admin_headers(),
        ),
        expected_status=201,
    )

    assert program["organ_type"] == "KIDNEY"
    assert program["cooling_off_days"] == 7
    assert program["follow_up_completeness_threshold_pct"] == 80
    assert program["follow_up_compliance_threshold_pct"] == 75
    assert program["expected_one_year_survival_rate"] == 0.95
    assert program["donor_fund_pool_cents"] == 5000000
    assert program["lost_wage_daily_cap_cents"] == 30000
    assert program["lost_wage_weekly_cap_cents"] == 150000
    assert program["donor_fund_committed_cents"] == 0
    assert program["donor_fund_remaining_cents"] == 5000000
    assert program["follow_up_compliance_pct"] == 100.0, (
        "the vacuous reading, because no follow-up interval is due yet"
    )
    assert program["cit_breach_count"] == 0
    assert program["compliance_posture"] == "OPEN"
    assert program["last_sweep_at"] is None
    assert program["version"] == 1
    assert program["created_at"].startswith("2026-08-01T00:00:00")


def test_recipient_creation_returns_declared_fields_and_creation_time_score():
    """PRD §3.2: "The new candidate's `listing_status` starts at `WORKUP`,
    `active_days_total` at 0, `offer_decline_count` at 0, and `waitlist_priority_score`
    is computed immediately — with zero accumulated waiting time, since the candidate
    has never been active."
    PRD §3.2: "The urgency component is `medical_urgency_points` multiplied by 2."
    PRD §3.2: "The dialysis component is `dialysis_years` multiplied by 1.005."
    PRD §3.2: "The sensitization component is a tier lookup on `cpra`, inclusive at
    each lower bound: 10 when `cpra` is at least 0.98, otherwise 4 when it is at least
    0.80, otherwise 1 when it is at least 0.20, otherwise 0."

    Design: Corner/entities/recipient_creation_returns_declared_fields_and_creation_time_score
    """
    env = setup_program_with_staff()

    recipient = validate_success(
        api_client.create_recipient_candidate(
            {
                "program_id": env["program_id"],
                "mrn": "R-101",
                "abo_blood_type": "A",
                "age_years": 44,
                "cpra": 0.85,
                "dialysis_years": 2.0,
                "medical_urgency_points": 7,
            },
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert recipient["listing_status"] == "WORKUP"
    assert recipient["active_days_total"] == 0
    assert recipient["waitlist_priority_score"] == 20.01, (
        "14.0 urgency + 0.0 waiting + 2.01 dialysis + 4.0 sensitization + 0.0 pediatric"
    )
    assert recipient["offer_decline_count"] == 0
    assert recipient["candidacy_approved_by_staff_id"] is None
    assert recipient["registered_at"] is None
    assert recipient["version"] == 1
    assert recipient["mrn"] == "R-101"
    assert recipient["abo_blood_type"] == "A"
    assert recipient["cpra"] == 0.85


def test_recipient_create_missing_required_cpra_returns_400():
    """PRD §3.2: "A coordinator opens a recipient workup by supplying the owning
    `program_id`, the patient's `mrn`, an `abo_blood_type` of `O`, `A`, `B` or `AB`, an
    `age_years` value of at least 0, and a `cpra` calculated panel reactive antibody
    fraction between 0 and 1 inclusive."
    PRD §2.6: "Request-shape validation, reported as `ERR_VALIDATION` (HTTP 400),
    covers a fixed list of conditions: every input field that has no default must be
    present; every enum-typed field must hold a declared member; integers and numbers
    must be of the right type and inside their declared range; cents-denominated fields
    must be non-negative integers; datetimes must be ISO 8601 UTC; `end_at` must be
    later than `start_at`, `period_end_on` must not precede `period_start_on`, and
    `service_to_on` must not precede `service_from_on`; `lost_wage_days` must be present
    and at least 1 exactly when `claim_type` is `LOST_WAGES` and must be absent
    otherwise; a reason code that a transition requires must be present — this covers
    `objection_reason_code`, `decline_reason_code`, `break_reason_code`,
    `waiver_reason_code`, `decision_reason_code` and `reversal_reason_code`; `limit`
    must lie in the inclusive range 1 to 100 and `offset` must be at least 0; and
    `observed_survivor_count` must not exceed `cohort_size`."

    Design: Corner/entities/recipient_create_missing_required_cpra_returns_400
    """
    env = setup_program_with_staff()

    response = api_client.create_recipient_candidate(
        {
            "program_id": env["program_id"],
            "mrn": "R-102",
            "abo_blood_type": "A",
            "age_years": 44,
        },
        env["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    assert _recipient_count(env) == 0, (
        "dialysis_years and medical_urgency_points default, but cpra does not"
    )


def test_recipient_create_computed_fields_input_ignored():
    """PRD §3.2: "The new candidate's `listing_status` starts at `WORKUP`,
    `active_days_total` at 0, `offer_decline_count` at 0, and `waitlist_priority_score`
    is computed immediately — with zero accumulated waiting time, since the candidate
    has never been active."
    PRD §3.2: "From `APPROVED_NOT_LISTED` the candidate may be registered on the
    waitlist by moving to `ACTIVE`; the first time this happens the candidate's
    `registered_at` is set to the supplied `effective_at`, and later re-entries into
    `ACTIVE` leave `registered_at` alone."
    PRD §3.2: "`offer_decline_count` on a candidate is the number of that candidate's
    chain segments currently sitting at `DECLINED`."

    Design: Corner/entities/recipient_create_computed_fields_input_ignored
    """
    env = setup_program_with_staff()

    recipient = validate_success(
        api_client.create_recipient_candidate(
            {
                "program_id": env["program_id"],
                "mrn": "R-103",
                "abo_blood_type": "A",
                "age_years": 44,
                "cpra": 0.85,
                "dialysis_years": 2.0,
                "medical_urgency_points": 7,
                "waitlist_priority_score": 99.0,
                "active_days_total": 500,
                "listing_status": "ACTIVE",
                "offer_decline_count": 7,
            },
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert recipient["waitlist_priority_score"] == 20.01, "recomputed, not the supplied 99.0"
    assert recipient["active_days_total"] == 0, "not the supplied 500"
    assert recipient["listing_status"] == "WORKUP", "not the supplied ACTIVE"
    assert recipient["offer_decline_count"] == 0, "not the supplied 7"
    assert recipient["registered_at"] is None, "no ACTIVE registration has happened"


def test_donor_create_system_fields_input_ignored():
    """PRD §3.3: "The referral records `referred_by_staff_id` from the referring
    coordinator's `X-User-ID` for provenance."
    PRD §3.3: "A new donor starts with `overall_status` `REFERRED`, `advocacy_status`
    `UNASSIGNED`, both `medical_status` and `psychosocial_status` at `PENDING`,
    `disclosure_sequence` 0, `deferral_count` 0, `medical_risk_points` and
    `psychosocial_risk_points` 0, and `screening_risk_index` 0; `advocate_staff_id`,
    `disclosure_at`, `cooling_off_ends_at`, `attestation_at`, `objection_reason_code`,
    `final_risk_index` and `donated_at` are all null."
    PRD §2.4: "Every persisted resource exposes an `id` that is a server-minted UUID
    with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three
    fractional digits."

    Design: Corner/entities/donor_create_system_fields_input_ignored
    """
    env = setup_program_with_staff()

    donor = validate_success(
        api_client.create_donor_candidate(
            {
                "program_id": env["program_id"],
                "mrn": "D-901",
                "abo_blood_type": "O",
                "age_years": 41,
                "id": NON_EXISTENT_UUID,
                "version": 42,
                "created_at": "2020-01-01T00:00:00Z",
                "overall_status": "APPROVED",
                "referred_by_staff_id": env["advocate"]["id"],
                "advocate_staff_id": env["advocate"]["id"],
                "advocacy_status": "ATTESTED",
            },
            env["coordinator_headers"],
        ),
        expected_status=201,
    )

    assert donor["id"] != NON_EXISTENT_UUID, "the identifier is server-minted"
    assert donor["version"] == 1
    assert donor["created_at"].startswith("2026-08-01T00:00:00"), "not 2020-01-01"
    assert donor["referred_by_staff_id"] == env["coordinator"]["id"], (
        "stamped from X-User-ID, not from the body"
    )
    assert donor["advocate_staff_id"] is None
    assert donor["advocacy_status"] == "UNASSIGNED", "not the supplied ATTESTED"
    assert donor["overall_status"] == "REFERRED", "not the supplied APPROVED"
    assert donor["medical_status"] == "PENDING"
    assert donor["psychosocial_status"] == "PENDING"
    assert donor["disclosure_sequence"] == 0
    assert donor["deferral_count"] == 0
    assert donor["screening_risk_index"] == 0
    assert donor["final_risk_index"] is None


def test_waitlist_status_event_rows_are_immutable_and_append_only():
    """PRD §2.4: "The one exception is the waitlist status event. A waitlist event is an
    immutable audit record: it carries only `id` and `created_at`. It has no
    `updated_at` and no `version`, because it is appended and never altered."
    PRD §3.2: "The operation both drives the candidate's `listing_status` and appends an
    immutable waitlist event recording the `recipient_candidate_id`, the `from_status`
    the candidate held, the `to_status` it moved to, the supplied `reason_code` and
    `effective_at`, and an `actor_user_id` taken from `X-User-ID`."
    PRD §3.2: "From `WORKUP` a candidate may go to `APPROVED_NOT_LISTED`, which
    additionally stamps `candidacy_approved_by_staff_id` with the approving
    coordinator's `X-User-ID`, or to `DECLINED`, which is terminal."

    Design: Corner/entities/waitlist_status_event_rows_are_immutable_and_append_only
    """
    env = setup_program_with_staff()
    recipient = create_recipient(env, mrn="R-001")
    update_recipient_status(
        env, recipient["id"], "APPROVED_NOT_LISTED", "WORKUP_COMPLETE", CLOCK_EPOCH
    )
    update_recipient_status(env, recipient["id"], "ACTIVE", "LISTED", CLOCK_EPOCH)

    rows, meta = validate_paginated(
        api_client.list_waitlist_events(
            recipient["id"], env["coordinator_headers"], params={"limit": 10, "offset": 0}
        )
    )

    assert meta["total_count"] == 2, "two updates append two rows, not one mutated row"
    assert meta["has_more"] is False
    assert rows[0]["from_status"] == "WORKUP"
    assert rows[0]["to_status"] == "APPROVED_NOT_LISTED"
    assert rows[0]["reason_code"] == "WORKUP_COMPLETE"
    assert rows[1]["from_status"] == "APPROVED_NOT_LISTED"
    assert rows[1]["to_status"] == "ACTIVE"
    assert rows[1]["reason_code"] == "LISTED"
    for row in rows:
        assert row["actor_user_id"] == env["coordinator"]["id"]
        assert row["effective_at"].startswith("2026-08-01T00:00:00")
        assert "version" not in row, "an append-only audit record carries no version"
        assert "updated_at" not in row

    listed = validate_success(
        api_client.get_recipient_candidate(recipient["id"], env["coordinator_headers"])
    )
    assert listed["registered_at"].startswith("2026-08-01T00:00:00")
    assert listed["candidacy_approved_by_staff_id"] == env["coordinator"]["id"]


def test_staff_member_listing_paginates_and_filters_by_role():
    """PRD §3.1: "Two program-scoped list capabilities are the only way to discover
    child rows by their owning program: the staff-member listing, which additionally
    filters on `staff_role` and `is_active`, and the operating-room listing, which
    exposes each room's `reserved_minutes_total`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching the
    filters before the page window is applied and `has_more` is true when rows remain
    beyond the current window."

    Design: Corner/entities/staff_member_listing_paginates_and_filters_by_role
    """
    env = setup_program_with_staff()

    filtered, filtered_meta = validate_paginated(
        api_client.list_program_staff_members(
            env["program_id"],
            env["admin_headers"],
            params={"staff_role": "EVALUATION_REVIEWER", "limit": 1, "offset": 0},
        )
    )
    assert filtered_meta["total_count"] == 2, (
        "the filter is applied before the page window, so the two reviewers are counted"
    )
    assert filtered_meta["has_more"] is True
    assert filtered_meta["limit"] == 1
    assert filtered_meta["offset"] == 0
    assert len(filtered) == 1
    assert filtered[0]["staff_role"] == "EVALUATION_REVIEWER"

    first_page, first_meta = validate_paginated(
        api_client.list_program_staff_members(
            env["program_id"], env["admin_headers"], params={"limit": 2, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 6, "the whole credentialed cast, unfiltered"
    assert first_meta["has_more"] is True
    assert len(first_page) == 2

    last_page, last_meta = validate_paginated(
        api_client.list_program_staff_members(
            env["program_id"], env["admin_headers"], params={"limit": 2, "offset": 5}
        )
    )
    assert last_meta["total_count"] == 6
    assert last_meta["has_more"] is False
    assert len(last_page) == 1


def test_chain_segment_junction_reverse_lookups_filter_correctly():
    """PRD §3.5: "Segments are listed with optional `exchange_chain_id`,
    `donor_candidate_id`, `recipient_candidate_id`, `predecessor_segment_id` and
    `status` filters plus `limit` and `offset`, and read individually to expose their
    planned and actual cold-ischemia figures and `cit_breach`."
    PRD §3.5: "Each insertion supplies the `expected_chain_version` described in §2.7,
    a 1-based `position` of at least 1, the `donor_candidate_id` giving in this segment,
    the `recipient_candidate_id` receiving in it, and an optional
    `predecessor_segment_id` naming the same chain's segment at the previous position —
    which must be null for the segment at position 1."

    Design: Corner/entities/chain_segment_junction_reverse_lookups_filter_correctly
    """
    env = setup_paired_loop_participants()
    build_paired_loop_chain(env)
    env["chain"] = validate_chain(env, env["chain"]["id"])
    segment_one, segment_two = env["segment_one"], env["segment_two"]

    by_predecessor, predecessor_meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"],
            params={
                "exchange_chain_id": env["chain"]["id"],
                "predecessor_segment_id": segment_one["id"],
            },
        )
    )
    assert predecessor_meta["total_count"] == 1
    assert by_predecessor[0]["id"] == segment_two["id"]
    assert by_predecessor[0]["position"] == 2
    assert by_predecessor[0]["donor_candidate_id"] == env["donor_two"]["id"]
    assert by_predecessor[0]["recipient_candidate_id"] == env["recipient_one"]["id"]

    by_donor, donor_meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"],
            params={"donor_candidate_id": env["donor_one"]["id"]},
        )
    )
    assert donor_meta["total_count"] == 1
    assert by_donor[0]["id"] == segment_one["id"]
    assert by_donor[0]["predecessor_segment_id"] is None

    by_recipient, recipient_meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"],
            params={"recipient_candidate_id": env["recipient_one"]["id"]},
        )
    )
    assert recipient_meta["total_count"] == 1
    assert by_recipient[0]["id"] == segment_two["id"]


def test_recipient_create_invalid_enum_and_out_of_range_cpra_rejected():
    """PRD §3.2: "A coordinator opens a recipient workup by supplying the owning
    `program_id`, the patient's `mrn`, an `abo_blood_type` of `O`, `A`, `B` or `AB`, an
    `age_years` value of at least 0, and a `cpra` calculated panel reactive antibody
    fraction between 0 and 1 inclusive."
    PRD §2.10: "Request shape, as specified in §2.6 — `ERR_VALIDATION`, 400."

    Design: Corner/entities/recipient_create_invalid_enum_and_out_of_range_cpra_rejected
    """
    env = setup_program_with_staff()

    response = api_client.create_recipient_candidate(
        {
            "program_id": env["program_id"],
            "mrn": "R-104",
            "abo_blood_type": "X",
            "age_years": 44,
            "cpra": 1.5,
        },
        env["coordinator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    assert _recipient_count(env) == 0


def test_chain_read_returns_topology_and_version_fields():
    """PRD §3.5: "Chains are listed with optional `program_id`, `chain_type` and `status`
    filters plus `limit` and `offset`, and read individually to expose `version`,
    `segment_count`, `is_closed_loop`, `total_planned_cit_minutes` and
    `committed_donor_count`."
    PRD §2.7: "Inserting a segment into a chain — `POST
    /exchange-chains/{id}/segments` — requires a non-optional `expected_chain_version`
    field carrying the client's last observed `version` of the target `ExchangeChain`."
    PRD §2.7: "A successful insertion increments the chain's `version`, which makes any
    other holder of the previous value stale."

    Design: Corner/entities/chain_read_returns_topology_and_version_fields
    """
    env = setup_paired_loop_participants()
    build_paired_loop_chain(env)
    version_at_creation = env["chain"]["version"]
    validate_chain(env, env["chain"]["id"])

    chain = validate_success(
        api_client.get_exchange_chain(env["chain"]["id"], env["coordinator_headers"])
    )

    assert chain["status"] == "VALIDATED"
    assert chain["validated_at"].startswith("2026-08-08T00:00:00")
    assert chain["segment_count"] == 2
    assert chain["is_closed_loop"] is True
    assert chain["total_planned_cit_minutes"] == 0
    assert chain["committed_donor_count"] == 0, "a VALIDATED chain commits nobody"
    assert chain["committed_at"] is None
    assert chain["break_reason_code"] is None
    assert isinstance(chain["version"], int)
    assert chain["version"] > version_at_creation, (
        "each segment insertion and the validation itself advanced the version"
    )


def test_program_read_is_the_reverse_lookup_for_a_missing_parent():
    """PRD §2.5: "The same codes cover foreign keys supplied in a request body rather
    than in the path."
    PRD §2.5: "Every reference — `program_id`, `intended_recipient_id`,
    `referred_by_staff_id`, `advocate_staff_id`, `donor_candidate_id`,
    `recipient_candidate_id`, `reviewer_staff_id`, `exchange_chain_id`,
    `predecessor_segment_id`, `operating_room_id`, `chain_segment_id`,
    `surgeon_staff_id` and `program_outcome_review_id` — must resolve to an existing
    row, and the failure reports the not-found code of the entity type that reference
    points at."
    PRD §2.10: "Every foreign key supplied in the request body exists — the matching
    not-found code, 404."

    Design: Corner/entities/program_read_is_the_reverse_lookup_for_a_missing_parent
    """
    program = create_program(name="Reverse Lookup Center", center_code="RLC-01")
    admin_headers = make_program_admin_headers()

    response = api_client.create_staff_member(
        {
            "program_id": NON_EXISTENT_UUID,
            "full_name": "Orphan Coordinator",
            "staff_role": "TRANSPLANT_COORDINATOR",
            "npi": "1000000099",
        },
        admin_headers,
    )
    validate_error(
        response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, expected_status=404
    )

    _rows, meta = validate_paginated(
        api_client.list_program_staff_members(program["id"], admin_headers)
    )
    assert meta["total_count"] == 0, "the well-shaped body created no row"
