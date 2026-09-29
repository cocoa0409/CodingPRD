"""
Role-based access control and the cross-cutting complexity layers of the
Concussion Protocol & Return-to-Play Administration API.

The first group walks the authority model of PRD §2.1 and the first rungs of the
refusal ladder of §2.5: header authentication, endpoint role authorisation, the
observer's non-delegable removal authority, clinician role identity, club scope
for both entity-backed club roles, consultant assignment, the compliance
officer's own operations, and auditor segregation of duties.

The second group walks the contract's cross-cutting layers: optimistic
concurrency on players and cases (§2.6), the compliance band edges and the
seven-step posture routine (§2.8), derived-field reconciliation across the audit
lifecycle (§3.10 / §2.12), the heightened-review flag that re-gates stage
sign-off (§3.6), and filter-plus-page interaction on a collection read (§2.3,
§2.12).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLUB_SCOPE_VIOLATION,
    ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED,
    ERR_INC_ASSIGNMENT_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_ROLE_IDENTITY_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CASE_VERSION,
    ERR_STALE_PLAYER_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_club_posture,
    assert_error_envelope,
    assert_exemption_slots,
    assert_ids_equal,
    assert_instant,
    assert_null,
    assert_page_meta,
    assert_return_step,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR_A,
    AUDITOR_B,
    AUDITOR_C,
    NO_HEADERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_club_physician_headers,
    make_compliance_officer_headers,
    make_consultant_headers,
    make_observer_headers,
)


# ─── Role-based access control ───────────────────────────────────────────────


def test_missing_or_unknown_role_header_is_unauthenticated(api):
    """Header authentication precedes every other rung of the refusal ladder.

    PRD: "If either header is absent, or if `X-User-Role` is not exactly one of
    the six recognised role names, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_rejected
    """
    # Arrange — one real club so the path resolves and only the headers can fail.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act / Assert — no headers at all.
    response = api.get_club(club["id"], NO_HEADERS)
    validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
    assert_error_envelope(response)

    # Act / Assert — X-User-Role absent.
    response = api.get_club(club["id"], headers_without_role("league-admin-ops"))
    validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
    assert_error_envelope(response)

    # Act / Assert — X-User-ID absent.
    response = api.get_club(club["id"], headers_without_user_id("LeagueAdmin"))
    validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
    assert_error_envelope(response)

    # Act / Assert — a role string outside the six recognised names.
    response = api.get_club(club["id"], headers_with_unknown_role("someone"))
    error = validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
    assert_error_envelope(response)

    # No club payload leaked through any refusal: the error data carries only the
    # error id and its message.
    assert set(error.keys()) == {"error_id", "message"}

    # The club itself is untouched and still readable by an authenticated caller.
    club_after = validate_success(api.get_club(club["id"], ADMIN), expected_status=200)
    assert club_after["name"] == "Harbor City Kraken"
    assert club_after["version"] == club["version"]


def test_club_physician_cannot_open_protocol_audit(api):
    """Opening an audit is the auditor's exclusive operation.

    PRD: "If the headers are well formed but the declared role is not among the
    roles the target endpoint permits, the refusal is `ERR_UNAUTHORIZED` (HTTP
    403)."

    Design: Corner/rbac/club_physician_cannot_open_protocol_audit
    """
    # Arrange — a fully credentialed club physician and their club.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    physician = fx.create_club_physician(api, club["id"], "Dr Vance", "LIC-1001")

    # Act — the physician tries to open an audit against their own club.
    response = api.create_protocol_audit(
        f.audit_payload(club_id=club["id"]), make_club_physician_headers(physician["id"])
    )

    # Assert — refused at the role-authorisation rung.
    validate_error(response, ERR_UNAUTHORIZED, expected_status=403)

    # Assert — the refused write left no trace: no audit row, no posture change.
    audits, meta = validate_paginated(api.list_protocol_audits(ADMIN, club_id=club["id"]))
    assert audits == []
    assert_page_meta(meta, total_count=0)
    club_after = fx.read_club(api, club["id"])
    assert club_after["open_violation_count"] == 0
    assert club_after["version"] == club["version"]


def test_club_physician_cannot_claim_observer_trigger_source(api):
    """Removal authority belongs to the unaffiliated observer and is not delegable.

    PRD: "An `UnaffiliatedObserver` may initiate for **any** player in the game
    regardless of club, and is the only role permitted to declare
    `trigger_source` `UNAFFILIATED_OBSERVER` — this is the observer's removal
    authority, and no other role can invoke it."

    Design: Corner/rbac/club_physician_cannot_claim_observer_trigger_source
    """
    # Arrange — the canonical live week-1 game with the club physician on duty.
    ctx = fx.setup_live_game(api)
    fx.set_clock(api, fx.EVALUATION_INITIATED_AT)

    # Act — the club physician claims the observer's trigger source.
    response = api.create_sideline_evaluation(
        f.evaluation_payload(
            ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
        ),
        ctx["doc_h_headers"],
    )

    # Assert — refused, and no evaluation row exists.  The contract forbids the
    # claim without naming the code it is refused with, so either the authority
    # refusal or the request refusal satisfies it.
    validate_error_is_one_of(response, [ERR_UNAUTHORIZED, ERR_INVALID_REQUEST])
    evaluations, meta = validate_paginated(api.list_sideline_evaluations(ADMIN))
    assert evaluations == []
    assert_page_meta(meta, total_count=0)

    # Act — the same physician's own trigger source is accepted on the same endpoint.
    allowed = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
            ),
            ctx["doc_h_headers"],
        ),
        expected_status=201,
    )

    # Assert — no mandatory removal, so the 45-minute deadline applies, not 15.
    assert allowed["trigger_source"] == "CLUB_MEDICAL_STAFF"
    assert allowed["mandatory_removal"] is False
    assert_instant(allowed["initiated_at"], "2026-09-13T18:05:00.000Z")
    assert_instant(allowed["protocol_deadline_at"], "2026-09-13T18:50:00.000Z")


def test_consultant_role_with_club_affiliated_identity_rejected(api):
    """A clinician-backed role must be paired with a matching clinician row.

    PRD: "For the three clinician-backed roles, if `X-User-ID` does not resolve
    to an existing `Clinician`, or resolves to a clinician whose `affiliation`
    does not match the declared role, the request is refused with
    `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/consultant_role_with_club_affiliated_identity_rejected
    """
    # Arrange — five stages passed and a PENDING clearance assigned to the consultant.
    ctx = fx.setup_case_pending_clearance(api)

    # Act — the club-affiliated physician wears the consultant hat.
    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(
            decision="APPROVED", decision_notes="club physician wearing the consultant hat"
        ),
        make_consultant_headers(ctx["doc_h_id"]),
    )
    validate_error(response, ERR_ROLE_IDENTITY_MISMATCH, expected_status=403)

    # Act — an identifier that is not a Clinician at all (a Club id).
    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(
            decision="APPROVED", decision_notes="club id used as a clinician id"
        ),
        make_consultant_headers(ctx["club_h_id"]),
    )
    validate_error(response, ERR_ROLE_IDENTITY_MISMATCH, expected_status=403)

    # Assert — neither refused decision was recorded anywhere.
    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "PENDING"
    assert_null(clearance, "decided_at", "expires_at")
    assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]), case_status="PENDING_INC_CLEARANCE"
    )


def test_writes_outside_the_actors_club_scope_rejected(api):
    """Both entity-backed club scoping rules refuse a write on another club's row.

    PRD: "When a `ClubComplianceOfficer` acts on another club's resource, or a
    `ClubPhysician` acts on a player or case belonging to another club, the
    refusal is `ERR_CLUB_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/writes_outside_the_actors_club_scope_rejected
    """
    # Arrange — two clubs, a Ridgeway physician, an un-baselined Harbor player and
    # a Harbor audit already priced.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    fx.create_club_physician(api, club_h["id"], "Dr Vance", "LIC-1001")
    doc_r = fx.create_club_physician(api, club_r["id"], "Dr Whitlock", "LIC-1201")
    player = fx.create_player(api, club_h["id"], "K Mbeki", 24, "WR")
    audit = fx.setup_audit_with_findings(api, club_h["id"], ["MISSED_MANDATORY_REMOVAL"], 0)

    # Act — the Ridgeway physician files a baseline for a Harbor City player.
    response = api.create_baseline_test(
        f.baseline_payload(
            player_id=player["id"], expected_player_version=player["version"]
        ),
        make_club_physician_headers(doc_r["id"]),
    )

    # Assert — refused at the physician-scope rung, and the player is untouched.
    validate_error(response, ERR_CLUB_SCOPE_VIOLATION, expected_status=403)
    player_after = fx.read_player(api, player["id"])
    assert player_after["baseline_status"] == "NONE"
    assert player_after["version"] == player["version"]
    tests, meta = validate_paginated(api.list_baseline_tests(ADMIN, player_id=player["id"]))
    assert tests == []
    assert_page_meta(meta, total_count=0)

    # Act — the Ridgeway compliance officer answers Harbor City's audit.
    response = api.respond_to_audit(
        audit["id"],
        f.audit_response_payload("not our audit"),
        make_compliance_officer_headers(club_r["id"]),
    )

    # Assert — refused at the club-officer-scope rung, and the audit is untouched.
    validate_error(response, ERR_CLUB_SCOPE_VIOLATION, expected_status=403)
    audit_after = fx.read_audit(api, audit["id"])
    assert audit_after["status"] == "FINDINGS_ISSUED"
    assert audit_after["response_round_count"] == 0
    assert_null(audit_after, "club_response_note")


def test_unassigned_consultant_cannot_decide_clearance(api):
    """Holding the consultant role is not enough; the clearance names its decider.

    PRD: "Only the assigned consultant may decide, and a decision by anyone else
    is refused with `ERR_INC_ASSIGNMENT_MISMATCH`."

    Design: Corner/rbac/unassigned_consultant_cannot_decide_clearance
    """
    # Arrange — a PENDING clearance assigned to one consultant, plus a second,
    # correctly affiliated but unassigned consultant.
    ctx = fx.setup_case_pending_clearance(api)
    fx.add_second_consultant(api, ctx, "Dr Halvorsen", "LIC-3002")

    # Act — the unassigned consultant decides.
    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(decision="APPROVED", decision_notes="not my patient"),
        ctx["inc2_headers"],
    )

    # Assert — refused, and the clearance is still awaiting its own consultant.
    validate_error(response, ERR_INC_ASSIGNMENT_MISMATCH, expected_status=403)
    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "PENDING"
    assert_null(clearance, "decided_at")

    # Act — the assigned consultant makes the identical call.
    approved = validate_success(
        api.decide_inc_clearance(
            ctx["clearance_id"],
            f.clearance_decision_payload(
                decision="APPROVED", decision_notes="independent review completed"
            ),
            ctx["inc_headers"],
        ),
        expected_status=200,
    )

    # Assert — approved, expiring exactly seven days after the decision.
    assert approved["status"] == "APPROVED"
    assert approved["inc_clinician_id"] == ctx["inc_id"]
    assert approved["documented_stage_count"] == 5
    assert_instant(approved["decided_at"], "2026-09-27T12:00:00.000Z")
    assert_instant(approved["expires_at"], "2026-10-04T12:00:00.000Z")


def test_compliance_officer_allowed_operations(api):
    """The compliance officer's own operations all succeed for their own club.

    PRD: "This read is restricted to `LeagueAdmin`, `LeagueAuditor` and
    `ClubComplianceOfficer`; the three clinician-backed roles may read every
    other collection but not this one."

    Design: Corner/rbac/compliance_officer_allowed_operations
    """
    # Arrange — the canonical diagnosed case, a later game inside its reporting
    # window, and one Harbor City audit already priced.
    ctx = fx.setup_diagnosed_case(api)
    later_game = fx.create_game(
        api,
        ctx["club_h_id"],
        ctx["club_r_id"],
        season_year=2026,
        week_index=3,
        kickoff_at="2026-10-01T17:00:00Z",
    )
    audit = fx.setup_audit_with_findings(
        api, ctx["club_h_id"], ["MISSED_MANDATORY_REMOVAL"], 0
    )
    fx.set_clock(api, "2026-09-30T00:00:00Z")
    officer = make_compliance_officer_headers(ctx["club_h_id"])

    # Act / Assert — rostering a player of the officer's own club.
    rostered = validate_success(
        api.create_player(
            f.player_payload(
                club_id=ctx["club_h_id"], full_name="V Ortiz", jersey_number=55, position="OL"
            ),
            officer,
        ),
        expected_status=201,
    )
    assert rostered["club_id"] == ctx["club_h_id"]

    # Act / Assert — granting the roster concussion exemption on the club's case.
    granted = validate_success(
        api.grant_roster_exemption(ctx["case_id"], officer), expected_status=200
    )
    assert_case_dimensions(granted, roster_exemption_status="GRANTED")

    # Act / Assert — filing the league injury report inside the open window.
    filed = validate_success(
        api.create_injury_report_entry(
            f.injury_report_payload(
                game_id=later_game["id"],
                player_id=ctx["player_id"],
                practice_participation="DNP",
                designation="OUT",
            ),
            officer,
        ),
        expected_status=201,
    )
    assert filed["designation"] == "OUT"
    assert filed["required_designation"] == "OUT"
    assert filed["status"] == "FILED"
    assert filed["club_id"] == ctx["club_h_id"]

    # Act / Assert — answering the club's own audit findings.
    responded = validate_success(
        api.respond_to_audit(
            audit["id"],
            f.audit_response_payload(
                "the observer's removal was honoured; documentation attached"
            ),
            officer,
        ),
        expected_status=200,
    )
    assert responded["status"] == "CLUB_RESPONDED"
    assert responded["response_round_count"] == 1
    assert responded["club_response_note"]

    # Act / Assert — the compliance summary read the clinician roles cannot see.
    summary = validate_success(
        api.get_compliance_summary(ctx["club_h_id"], officer), expected_status=200
    )
    assert summary["club_id"] == ctx["club_h_id"]
    # A CLUB_RESPONDED audit stays inside the preliminary included set, so the
    # 18-point MISSED_MANDATORY_REMOVAL weight still bites while the adjudicated
    # figure is untouched.
    assert_club_posture(
        summary,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )
    assert_exemption_slots(summary, used=1, available=2, total=3)
    assert summary["frozen_case_count"] == 0


def test_audit_closer_cannot_be_the_findings_issuer(api):
    """The close step is fenced off from the pricing step.

    PRD: "Closing an audit adjudicates it, supplies a `disposition` and an
    optional `closing_note`, and is again reserved for a different auditor: an
    auditor whose identifier equals `findings_issued_by_user_id` closing the
    audit is refused with `ERR_SEGREGATION_OF_DUTIES`, and that comparison is
    skipped whenever `findings_issued_by_user_id` is null, as it is for
    auto-issued findings."

    Design: Corner/rbac/audit_closer_cannot_be_the_findings_issuer
    """
    # Arrange — opened by auditor-a, priced by auditor-b.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
    priced = fx.issue_findings(
        api, audit["id"], ["MISSED_MANDATORY_REMOVAL"], 0, issuer_headers=AUDITOR_B
    )
    assert priced["findings_issued_by_user_id"] == "auditor-b"

    # Act — the issuing auditor tries to close their own findings.
    response = api.close_audit(
        audit["id"],
        f.audit_close_payload(
            disposition="UPHELD", closing_note="issuer trying to close his own findings"
        ),
        AUDITOR_B,
    )

    # Assert — refused, and the audit is still open for adjudication.
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    audit_after = fx.read_audit(api, audit["id"])
    assert audit_after["status"] == "FINDINGS_ISSUED"
    assert audit_after["disposition"] == "PENDING"
    assert_null(audit_after, "closed_at", "closed_by_user_id")

    # Act — a third auditor closes it.
    closed = validate_success(
        api.close_audit(
            audit["id"],
            f.audit_close_payload(
                disposition="UPHELD", closing_note="independent review completed"
            ),
            AUDITOR_C,
        ),
        expected_status=200,
    )

    # Assert — upheld by auditor-c, and the adjudicated score now absorbs the weights.
    assert closed["status"] == "CLOSED_UPHELD"
    assert closed["disposition"] == "UPHELD"
    assert closed["closed_by_user_id"] == "auditor-c"
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=0,
        adjudicated_compliance_score=82,
    )


# ─── Cross-cutting complexity layers ────────────────────────────────────────


def test_stale_player_version_rejected_on_baseline_filing(api):
    """A superseding baseline must quote the player version the client read.

    PRD: "If that value does not equal the player's current `version` — for
    instance because a diagnosis has since flipped `baseline_status` to
    `RETEST_REQUIRED` — the request is rejected with `ERR_STALE_PLAYER_VERSION`
    (HTTP 412), and the client must re-read the player before retrying."

    Design: Corner/cross-cutting complexity layers/stale_player_version_rejected
    """
    # Arrange — one baseline already on file, filed against the player at version 1.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    physician = fx.create_club_physician(api, club["id"], "Dr Vance", "LIC-1001")
    player = fx.create_player(api, club["id"], "K Mbeki", 24, "WR")
    player_v1 = player["version"]
    first = fx.file_baseline(
        api, player["id"], physician["id"], expected_player_version=player_v1
    )

    # Act — reuse the version that was valid before that first filing.
    response = api.create_baseline_test(
        f.baseline_payload(
            player_id=player["id"],
            expected_player_version=player_v1,
            composite_score=84,
            reaction_time_ms=540,
        ),
        make_club_physician_headers(physician["id"]),
    )

    # Assert — refused, and the refused write left no trace at all.
    validate_error(response, ERR_STALE_PLAYER_VERSION, expected_status=412)
    assert fx.read_baseline(api, first["id"])["status"] == "VALID"
    tests, meta = validate_paginated(api.list_baseline_tests(ADMIN, player_id=player["id"]))
    assert_page_meta(meta, total_count=1)
    assert_ids_equal(tests, [first["id"]])

    # Assert — the successful filing had advanced the player by exactly one.
    player_now = fx.read_player(api, player["id"])
    assert player_now["version"] == player_v1 + 1

    # Act — the identical payload succeeds once the client re-reads the player.
    retry = validate_success(
        api.create_baseline_test(
            f.baseline_payload(
                player_id=player["id"],
                expected_player_version=player_now["version"],
                composite_score=84,
                reaction_time_ms=540,
            ),
            make_club_physician_headers(physician["id"]),
        ),
        expected_status=201,
    )

    # Assert — the fresh row supersedes the old one and the player advances past
    # the version the retry quoted, so the same body could not be replayed again.
    assert retry["status"] == "VALID"
    assert fx.read_baseline(api, first["id"])["status"] == "SUPERSEDED"
    player_final = fx.read_player(api, player["id"])
    assert player_final["baseline_status"] == "VALID"
    assert player_final["version"] > player_now["version"]


def test_stale_case_version_rejected_on_clearance_request(api):
    """The clearance request must quote the case version the requester read.

    PRD: "Any earlier write to that case — a stage pass, a revocation, a
    club-posture freeze — has already advanced its `version`, so a stale value is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_case_version_rejected
    """
    # Arrange — all five stages passed and the post-diagnosis retest on file.
    ctx = fx.setup_case_all_stages_passed(api)
    fx.file_baseline_retest(api, ctx)
    case_v = fx.case_version(api, ctx["case_id"])

    # Act — request clearance one version behind the current row.
    response = api.request_inc_clearance(
        ctx["case_id"],
        f.clearance_request_payload(ctx["inc_id"], case_v - 1),
        ctx["doc_h_headers"],
    )

    # Assert — refused, and no clearance row was minted.
    validate_error(response, ERR_STALE_CASE_VERSION, expected_status=412)
    clearances, meta = validate_paginated(
        api.list_inc_clearances(ADMIN, case_id=ctx["case_id"])
    )
    assert clearances == []
    assert_page_meta(meta, total_count=0)
    case_after = fx.read_case(api, ctx["case_id"])
    assert_case_dimensions(case_after, case_status="RTP_IN_PROGRESS")
    assert case_after["version"] == case_v

    # Act — the current version succeeds.
    requested = validate_success(
        api.request_inc_clearance(
            ctx["case_id"],
            f.clearance_request_payload(ctx["inc_id"], case_v),
            ctx["doc_h_headers"],
        ),
        expected_status=201,
    )

    # Assert — a PENDING clearance and the case advanced by exactly one version.
    assert requested["status"] == "PENDING"
    assert_instant(requested["requested_at"], "2026-09-27T12:00:00.000Z")
    case_final = fx.read_case(api, ctx["case_id"])
    assert_case_dimensions(case_final, case_status="PENDING_INC_CLEARANCE")
    assert case_final["version"] == case_v + 1


def test_escalation_tier_and_posture_band_boundaries(api):
    """Four fresh clubs land on the four compliance band edges in one run.

    PRD: "Both band sets are closed intervals exactly as written; a club scoring
    exactly 89 is `TIER_1` and on `PROBATION`, and a club scoring exactly 70 is
    on `PROBATION` rather than `SANCTIONED`."

    Design: Corner/cross-cutting complexity layers/escalation_tier_and_posture_band_boundaries
    """
    # Arrange — four clubs with no audit history, one OPEN audit each.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    clubs = {
        "A": fx.create_club(api, "Band A FC", "BDA", 1),
        "B": fx.create_club(api, "Band B FC", "BDB", 1),
        "C": fx.create_club(api, "Band C FC", "BDC", 1),
        "D": fx.create_club(api, "Band D FC", "BDD", 1),
    }
    audits = {
        key: fx.open_audit(api, club["id"], opener_headers=AUDITOR_A)
        for key, club in clubs.items()
    }

    # Each code set is chosen so the summed weights land on a band edge; with
    # exposure_days 0 the exposure factor is exactly 1, the severity factor is
    # 1.00 (no case named), and the stamped TIER_0 multiplier is 1.00.
    code_sets = {
        "A": ["UNAUTHORIZED_SAME_GAME_RETURN"],
        "B": ["MISSING_INC_CLEARANCE", "LATE_INJURY_REPORT"],
        "C": ["MISSED_MANDATORY_REMOVAL", "INCOMPLETE_LOCKER_ROOM_EXAM"],
        "D": ["UNAUTHORIZED_SAME_GAME_RETURN", "LATE_INJURY_REPORT"],
    }

    # Act — price each audit as an auditor other than its opener.
    for key, codes in code_sets.items():
        priced = validate_success(
            api.issue_findings(
                audits[key]["id"],
                f.findings_payload(violation_codes=codes, exposure_days=0),
                AUDITOR_B,
            ),
            expected_status=200,
        )
        # The tier used to price is read with this audit excluded, so each club
        # was still at 100 and therefore TIER_0.
        assert priced["escalation_tier_at_issuance"] == "TIER_0"

    # Assert — 75 is TIER_1/PROBATION, 74 is TIER_2/PROBATION, exactly 70 is
    # still PROBATION, and 69 tips into SANCTIONED.
    assert_club_posture(
        fx.read_club(api, clubs["A"]["id"]),
        compliance_score=75,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=25000000,
    )
    assert_club_posture(
        fx.read_club(api, clubs["B"]["id"]),
        compliance_score=74,
        escalation_tier="TIER_2",
        status="PROBATION",
        outstanding_fine_cents=21500000,
    )
    assert_club_posture(
        fx.read_club(api, clubs["C"]["id"]),
        compliance_score=70,
        escalation_tier="TIER_2",
        status="PROBATION",
        outstanding_fine_cents=22500000,
    )
    assert_club_posture(
        fx.read_club(api, clubs["D"]["id"]),
        compliance_score=69,
        escalation_tier="TIER_2",
        status="SANCTIONED",
        outstanding_fine_cents=26500000,
    )


def test_derived_fields_reconcile_across_the_audit_lifecycle(api):
    """The club ledger is recomputed from scratch at each step, never incremented.

    PRD: "Because `CLOSED_UPHELD` sits inside both included sets,
    `compliance_score` and `outstanding_fine_cents` do not move; what changes is
    that `adjudicated_compliance_score` now drops to absorb the audit's weights
    and `open_violation_count` falls by 1."

    Design: Corner/cross-cutting complexity layers/derived_fields_reconcile_across_the_audit_lifecycle
    """
    # Arrange — one club with a clean sheet.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)

    # Act / Assert — OPEN: counted as an open violation but priced at nothing.
    audit = validate_success(
        api.create_protocol_audit(f.audit_payload(club_id=club["id"]), AUDITOR_A),
        expected_status=201,
    )
    assert audit["status"] == "OPEN"
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=100,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=0,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )

    # Act / Assert — FINDINGS_ISSUED: the preliminary score absorbs 18 points and
    # the fine lands, while the adjudicated score stays at 100.
    priced = validate_success(
        api.issue_findings(
            audit["id"],
            f.findings_payload(violation_codes=["MISSED_MANDATORY_REMOVAL"], exposure_days=0),
            AUDITOR_B,
        ),
        expected_status=200,
    )
    assert priced["status"] == "FINDINGS_ISSUED"
    assert priced["assessed_fine_cents"] == 15000000
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )

    # Act / Assert — CLUB_RESPONDED: responding changes no arithmetic at all.
    responded = validate_success(
        api.respond_to_audit(
            audit["id"],
            f.audit_response_payload("documentation attached"),
            make_compliance_officer_headers(club["id"]),
        ),
        expected_status=200,
    )
    assert responded["status"] == "CLUB_RESPONDED"
    assert responded["response_round_count"] == 1
    assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=1,
        adjudicated_compliance_score=100,
    )

    # Act / Assert — CLOSED_UPHELD: the open count falls without refunding the fine.
    closed = validate_success(
        api.close_audit(audit["id"], f.audit_close_payload(disposition="UPHELD"), AUDITOR_C),
        expected_status=200,
    )
    assert closed["status"] == "CLOSED_UPHELD"

    # Assert — the computed projection agrees with the stored club row.
    summary = validate_success(
        api.get_compliance_summary(club["id"], AUDITOR_C), expected_status=200
    )
    assert_club_posture(
        summary,
        compliance_score=82,
        escalation_tier="TIER_1",
        status="PROBATION",
        outstanding_fine_cents=15000000,
        open_violation_count=0,
        adjudicated_compliance_score=82,
    )


def test_heightened_review_flag_toggles_stage_signoff_authority(api):
    """Club posture re-gates which of the club's physicians may sign a stage off.

    PRD: "Where the case carries `heightened_review_required`, the signing
    physician must not be the case's `diagnosing_clinician_id`; the club's own
    diagnosing clinician signing off a stage under heightened review is refused
    with `ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED`."

    Design: Corner/cross-cutting complexity layers/heightened_review_flag_toggles_stage_signoff_authority
    """
    # Arrange — stage 1 open since 2026-09-15T12:00:00Z, plus a second physician.
    ctx = fx.setup_case_with_stage_open(api, 1)
    fx.add_second_physician(api, ctx, "Dr Nakamura", "LIC-1002")
    step1_id = ctx["step_ids"][1]

    # Assert — while the club is ACTIVE the flag is off.
    case_before = fx.read_case(api, ctx["case_id"])
    assert case_before["heightened_review_required"] is False
    assert case_before["diagnosing_clinician_id"] == ctx["doc_h_id"]

    # Act — findings drive the club to 82 points, which is PROBATION.
    fx.setup_audit_with_findings(api, ctx["club_h_id"], ["MISSED_MANDATORY_REMOVAL"], 0)

    # Assert — the flag turns on, but 82 is above 70 so nothing is frozen.
    club = fx.read_club(api, ctx["club_h_id"])
    assert club["compliance_score"] == 82
    assert club["status"] == "PROBATION"
    case_flagged = fx.read_case(api, ctx["case_id"])
    assert case_flagged["heightened_review_required"] is True
    assert_case_dimensions(case_flagged, case_status="RTP_IN_PROGRESS")
    assert_null(case_flagged, "frozen_from_status")

    # Act — the diagnosing physician signs the stage off at its dwell instant.
    fx.set_clock(api, "2026-09-16T12:00:00Z")
    response = api.evaluate_return_step(
        step1_id, f.evaluate_step_payload(outcome="PASS", symptom_score=0), ctx["doc_h_headers"]
    )

    # Assert — refused, and the step is untouched.
    validate_error(response, ERR_HEIGHTENED_REVIEW_CLINICIAN_REQUIRED, expected_status=403)
    refused_step = fx.read_step(api, step1_id)
    assert_return_step(refused_step, stage_index=1, status="IN_PROGRESS")
    assert_null(refused_step, "evaluated_at", "cleared_by_clinician_id")

    # Act — a second club physician signs the identical stage off.
    passed = validate_success(
        api.evaluate_return_step(
            step1_id,
            f.evaluate_step_payload(outcome="PASS", symptom_score=0),
            ctx["doc_h2_headers"],
        ),
        expected_status=200,
    )

    # Assert — the rung is passed and the ladder advances.
    assert_return_step(passed, stage_index=1, status="PASSED")
    assert passed["cleared_by_clinician_id"] == ctx["doc_h2_id"]
    case_after = fx.read_case(api, ctx["case_id"])
    assert case_after["rtp_stage"] == 1
    assert_case_dimensions(case_after, case_status="RTP_IN_PROGRESS")


def test_case_listing_filter_and_page_interaction(api):
    """Filtering runs before paging on the concussion-case collection read.

    PRD: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates
    whether rows remain beyond the current page."

    Design: Corner/cross-cutting complexity layers/case_listing_filter_and_page_interaction
    """
    # Arrange — two players of one club diagnosed in the same live game, so both
    # cases sit in MANDATORY_REMOVAL, and a second club with no cases at all.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club_n = fx.create_club(api, "Northshore Pilots", "NSP", 2)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    doc_n = fx.create_club_physician(api, club_n["id"], "Dr Nkemi", "LIC-1101")
    observer = fx.create_observer(api)
    consultant = fx.create_consultant(api)
    doc_headers = make_club_physician_headers(doc_n["id"])
    obs_headers = make_observer_headers(observer["id"])

    player_1 = fx.create_player(api, club_n["id"], "P Novak", 11, "QB")
    player_2 = fx.create_player(api, club_n["id"], "S Okafor", 12, "RB")
    fx.file_baseline(api, player_1["id"], doc_n["id"], composite_score=88, reaction_time_ms=520)
    fx.file_baseline(api, player_2["id"], doc_n["id"], composite_score=88, reaction_time_ms=525)

    game = fx.create_game(
        api,
        club_n["id"],
        club_r["id"],
        season_year=2026,
        week_index=2,
        kickoff_at="2026-09-20T17:00:00Z",
    )
    fx.set_clock(api, "2026-09-20T17:00:00Z")
    fx.advance_game(api, game["id"], "IN_PROGRESS")

    # First case: examination attended by the observer, diagnosed nine minutes in.
    fx.set_clock(api, "2026-09-20T18:00:00Z")
    eval_1 = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                player_1["id"], game["id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            obs_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.screen_evaluation(
            eval_1["id"], f.screen_payload(no_go_signs=["ATAXIA"], symptom_score=9), doc_headers
        ),
        expected_status=200,
    )
    validate_success(
        api.start_locker_room_exam(
            eval_1["id"], f.locker_room_exam_payload(observer["id"]), doc_headers
        ),
        expected_status=200,
    )
    fx.set_clock(api, "2026-09-20T18:09:00Z")
    case_1 = validate_success(
        api.diagnose_concussion(
            eval_1["id"], f.diagnose_payload(symptom_score=9, composite_score=70), doc_headers
        ),
        expected_status=201,
    )

    # Second case: the observer's own block is still live, so the independent
    # consultant attends this examination instead.
    fx.set_clock(api, "2026-09-20T18:10:00Z")
    eval_2 = validate_success(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                player_2["id"], game["id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            obs_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.screen_evaluation(
            eval_2["id"], f.screen_payload(no_go_signs=["ATAXIA"], symptom_score=9), doc_headers
        ),
        expected_status=200,
    )
    validate_success(
        api.start_locker_room_exam(
            eval_2["id"], f.locker_room_exam_payload(consultant["id"]), doc_headers
        ),
        expected_status=200,
    )
    fx.set_clock(api, "2026-09-20T18:19:00Z")
    case_2 = validate_success(
        api.diagnose_concussion(
            eval_2["id"], f.diagnose_payload(symptom_score=9, composite_score=70), doc_headers
        ),
        expected_status=201,
    )

    # Act / Assert — page one of the filtered set: total_count counts both rows.
    rows, meta = validate_paginated(
        api.list_concussion_cases(
            ADMIN,
            club_id=club_n["id"],
            case_status="MANDATORY_REMOVAL",
            limit=1,
            offset=0,
        )
    )
    assert_page_meta(meta, total_count=2, limit=1, offset=0, has_more=True)
    assert_ids_equal(rows, [case_1["id"]])

    # Act / Assert — page two exhausts the filtered set.
    rows_2, meta_2 = validate_paginated(
        api.list_concussion_cases(
            ADMIN,
            club_id=club_n["id"],
            case_status="MANDATORY_REMOVAL",
            limit=1,
            offset=1,
        )
    )
    assert_page_meta(meta_2, total_count=2, limit=1, offset=1, has_more=False)
    assert_ids_equal(rows_2, [case_2["id"]])
    assert rows_2[0]["id"] != rows[0]["id"]

    # Act / Assert — the same filter scoped to the other club matches nothing.
    rows_3, meta_3 = validate_paginated(
        api.list_concussion_cases(
            ADMIN, club_id=club_r["id"], case_status="MANDATORY_REMOVAL"
        )
    )
    assert rows_3 == []
    assert_page_meta(meta_3, total_count=0)

    # Act / Assert — unpaged, the envelope defaults apply.
    rows_4, meta_4 = validate_paginated(
        api.list_concussion_cases(ADMIN, club_id=club_n["id"])
    )
    assert_page_meta(meta_4, total_count=2, limit=10, offset=0, has_more=False)
    assert_ids_equal(rows_4, [case_1["id"], case_2["id"]])
