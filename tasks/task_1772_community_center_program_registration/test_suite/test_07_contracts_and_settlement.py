"""Contract acceptance identity, publish gating, and instructor settlement
under both bases with pinned per-line rounding."""
from test_helpers import (
    AFTER_ALL_MEETINGS,
    MEETING_TIMES_4,
    PC,
    ApiErrorId,
    accept_contract,
    add_meeting,
    create_class_session,
    create_contract,
    create_instructor,
    create_program,
    create_published_season,
    create_room,
    create_verified_safety_form,
    get_contract,
    mark_present,
    register_and_pay,
    register_participant,
    run_sweep,
    set_clock,
    setup_household_with_participants,
    setup_household_with_scholarship,
    setup_multi_session_catalog,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import make_instructor_headers, drop_registration


def test_publish_rejected_while_contract_offered(api):
    """PRD §3.3: "The owning season must be `PUBLISHED`, else
    `ERR_SEASON_NOT_PUBLISHED`. An `ACCEPTED` contract must exist for the
    session and its assigned instructor, else `ERR_CONTRACT_NOT_ACCEPTED`. The
    session must have at least one class meeting, else `ERR_NO_MEETINGS`."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_accepted_contract
    """
    season = create_published_season()
    program = create_program(season["id"], name="Piano", category="Arts")
    room = create_room(name="Music Room")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"],
                                   title="Piano Basics")
    add_meeting(session["id"], room["id"])
    create_contract(session["id"], instructor["id"])   # stays OFFERED

    resp = _api.publish_class_session(session["id"], PC)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACCEPTED, 409)


def test_publish_succeeds_after_contract_accepted(api):
    """PRD §3.3: "An `ACCEPTED` contract must exist for the session and its
    assigned instructor, else `ERR_CONTRACT_NOT_ACCEPTED`."
    PRD §3.3: "The named instructor — and only that instructor, by
    entity-backed identity — may accept it, moving it to `ACCEPTED`, provided
    the session is still `DRAFT` or `PUBLISHED`; accepting under any other
    session state is `ERR_INVALID_STATE`, and a different instructor
    attempting the accept is `ERR_UNAUTHORIZED_ROLE`."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_accepted_contract
    """
    season = create_published_season()
    program = create_program(season["id"], name="Piano", category="Arts")
    room = create_room(name="Music Room")
    instructor = create_instructor()
    session = create_class_session(program["id"], instructor["id"],
                                   title="Piano Basics")
    add_meeting(session["id"], room["id"])
    contract = create_contract(session["id"], instructor["id"])

    accept_contract(contract["id"], instructor["id"])
    published = validate_success(_api.publish_class_session(session["id"], PC))
    assert published["status"] == "PUBLISHED"


def _settle(ctx: dict) -> dict:
    """Activate via the sweep, move past the last meeting, complete, and
    return the settled contract."""
    set_clock(ctx["session"]["enrollment_check_at"])
    run_sweep(ctx["season"]["id"])
    set_clock(AFTER_ALL_MEETINGS)
    validate_success(_api.complete_class_session(ctx["session"]["id"], PC))
    return get_contract(ctx["contract"]["id"])


def test_settlement_enrollment_basis_counts_all_enrolled(api):
    """PRD §3.9: "Under `ENROLLMENT_BASIS`, every registration still
    `ENROLLED` at completion counts." and "Each counted registration then
    contributes a line equal to its `net_paid_cents` multiplied by the
    contract's `revenue_share_bp` and divided by ten thousand, rounded half-up
    to a whole cent — each line rounded first, then the rounded lines summed;
    summing raw fractions and rounding once is a different, non-conforming
    algorithm. `settlement_headcount` records the number of counted
    registrations, and `settlement_amount_cents` is the greater of the
    contract's `guarantee_min_cents` and the summed subtotal; `payout_cents`
    equals `settlement_amount_cents`."

    Design: Difficulty/dual_variant_calc/instructor_settlement_basis_divergence
    """
    catalog = setup_multi_session_catalog([
        {"title": "SE", "fee_resident_cents": 10000, "fee_nonresident_cents": 10000,
         "meeting_times": MEETING_TIMES_4,
         "contract_overrides": {"settlement_basis": "ENROLLMENT_BASIS",
                                "revenue_share_bp": 5000}},
    ])
    ctx = {"season": catalog["season"], **catalog["sessions"][0]}
    household, parts = setup_household_with_participants(count=2, account_name="HH",
                                                         name_prefix="Pat")
    register_and_pay(ctx["session"]["id"], parts[0]["id"], household["id"])
    register_and_pay(ctx["session"]["id"], parts[1]["id"], household["id"])

    contract = _settle(ctx)
    # Two counted registrations x round_half_up(10000 * 5000 / 10000) == 5000.
    assert contract["status"] == "SETTLED"
    assert contract["settlement_headcount"] == 2
    assert contract["settlement_amount_cents"] == 10000
    assert contract["payout_cents"] == 10000


def test_settlement_attendance_basis_gates_below_fifty(api):
    """PRD §3.9: "Under `ATTENDANCE_BASIS`, a registration counts only when it
    is still `ENROLLED` at completion and its attendance percentage reaches
    the qualifying mark of fifty percent — a percentage of exactly fifty
    qualifies; the percentage is zero when no meeting of the session has been
    held, and otherwise one hundred times the registration's `PRESENT` marks
    on meetings already held, divided by the number of meetings held."

    Design: Difficulty/dual_variant_calc/instructor_settlement_basis_divergence
    """
    catalog = setup_multi_session_catalog([
        {"title": "SA", "fee_resident_cents": 10000, "fee_nonresident_cents": 10000,
         "meeting_times": MEETING_TIMES_4,
         "contract_overrides": {"settlement_basis": "ATTENDANCE_BASIS",
                                "revenue_share_bp": 5000}},
    ])
    ctx = {"season": catalog["season"], **catalog["sessions"][0]}
    household, parts = setup_household_with_participants(
        count=2, account_name="HH", name_prefix="Pat",
        birth_dates=("2015-01-01T00:00:00Z", "2016-01-01T00:00:00Z"),
    )
    ra1 = register_and_pay(ctx["session"]["id"], parts[0]["id"], household["id"])
    ra2 = register_and_pay(ctx["session"]["id"], parts[1]["id"], household["id"])
    # Minors: guardian-signed forms, verified for the season.
    for part in parts:
        create_verified_safety_form(part["id"], catalog["season"]["id"],
                                    household["id"], signer_name="Guardian One")

    set_clock(ctx["session"]["enrollment_check_at"])
    run_sweep(catalog["season"]["id"])
    set_clock(AFTER_ALL_MEETINGS)
    # P1 attends all four meetings (100%); P2 attends only the first (25%).
    instructor_id = ctx["instructor"]["id"]
    for meeting in ctx["meetings"]:
        mark_present(meeting["id"], ra1["id"], instructor_id)
    mark_present(ctx["meetings"][0]["id"], ra2["id"], instructor_id)

    validate_success(_api.complete_class_session(ctx["session"]["id"], PC))
    contract = get_contract(ctx["contract"]["id"])
    # 100% >= 50 counts; 25% < 50 is excluded -> 1 x 5000.
    assert contract["status"] == "SETTLED"
    assert contract["settlement_headcount"] == 1
    assert contract["settlement_amount_cents"] == 5000
    assert contract["payout_cents"] == 5000


def _per_line_scenario() -> dict:
    """One-meeting session at 2500/2500 with a 3333bp ENROLLMENT_BASIS
    contract; two households each holding an APPROVED 50% scholarship, each
    registered (fee 1250) and paid."""
    catalog = setup_multi_session_catalog(
        [{"title": "Chess Club", "fee_resident_cents": 2500,
          "fee_nonresident_cents": 2500,
          "contract_overrides": {"revenue_share_bp": 3333}}],
        season_overrides={"scholarship_budget_cents": 100000},
    )
    ctx = {"season": catalog["season"], **catalog["sessions"][0]}
    for name in ("H1", "H2"):
        household, parts, _app = setup_household_with_scholarship(
            catalog["season"]["id"], 50, 2000, count=1, account_name=name,
            name_prefix="Play",
        )
        register_and_pay(ctx["session"]["id"], parts[0]["id"], household["id"])
    return ctx


def test_settlement_rounds_each_line_before_summing(api):
    """PRD §3.9: "Each counted registration then contributes a line equal to
    its `net_paid_cents` multiplied by the contract's `revenue_share_bp` and
    divided by ten thousand, rounded half-up to a whole cent — each line
    rounded first, then the rounded lines summed; summing raw fractions and
    rounding once is a different, non-conforming algorithm.
    `settlement_headcount` records the number of counted registrations, and
    `settlement_amount_cents` is the greater of the contract's
    `guarantee_min_cents` and the summed subtotal; `payout_cents` equals
    `settlement_amount_cents`."

    Design: Difficulty/combinatorial_formula/instructor_pay_per_line_rounding
    """
    ctx = _per_line_scenario()
    contract = _settle(ctx)
    # Per line: round_half_up(1250 * 3333 / 10000) == 417; 417 + 417 == 834
    # (sum-then-round would yield 833).
    assert contract["settlement_headcount"] == 2
    assert contract["settlement_amount_cents"] == 834


def test_settlement_payout_equals_rounded_amount(api):
    """PRD §3.9: "`settlement_amount_cents` is the greater of the contract's
    `guarantee_min_cents` and the summed subtotal; `payout_cents` equals
    `settlement_amount_cents`."
    PRD §3.9: "Completion settles the instructor: the session's `ACCEPTED`
    contract moves to `SETTLED`; a contract still `OFFERED` is voided with
    `payout_cents` zero; a `DECLINED` one is untouched."

    Design: Difficulty/combinatorial_formula/instructor_pay_per_line_rounding
    """
    ctx = _per_line_scenario()
    contract = _settle(ctx)
    assert contract["status"] == "SETTLED"
    assert contract["payout_cents"] == 834
    assert contract["payout_cents"] == contract["settlement_amount_cents"]


def test_attendance_pct_exactly_fifty_qualifies(api):
    """PRD §3.9: "Under `ATTENDANCE_BASIS`, a registration counts only when it
    is still `ENROLLED` at completion and its attendance percentage reaches
    the qualifying mark of fifty percent — a percentage of exactly fifty
    qualifies; the percentage is zero when no meeting of the session has been
    held, and otherwise one hundred times the registration's `PRESENT` marks
    on meetings already held, divided by the number of meetings held."

    Design: Corner/calculations/attendance_pct_boundary_qualifies
    """
    catalog = setup_multi_session_catalog([
        {"title": "Track", "fee_resident_cents": 10000, "fee_nonresident_cents": 10000,
         "meeting_times": MEETING_TIMES_4,
         "contract_overrides": {"settlement_basis": "ATTENDANCE_BASIS"}},
    ])
    ctx = {"season": catalog["season"], **catalog["sessions"][0]}
    household, parts = setup_household_with_participants(count=1, account_name="HD",
                                                         name_prefix="Dash")
    registration = register_and_pay(ctx["session"]["id"], parts[0]["id"],
                                    household["id"])
    # Adult participant self-signs (age >= 18 at the season start).
    create_verified_safety_form(parts[0]["id"], catalog["season"]["id"],
                                household["id"], signer_name=parts[0]["full_name"])

    set_clock(ctx["session"]["enrollment_check_at"])
    run_sweep(catalog["season"]["id"])
    set_clock(AFTER_ALL_MEETINGS)
    # Two of four meetings PRESENT: attendance_pct == 50 exactly.
    instructor_id = ctx["instructor"]["id"]
    mark_present(ctx["meetings"][0]["id"], registration["id"], instructor_id)
    mark_present(ctx["meetings"][1]["id"], registration["id"], instructor_id)

    validate_success(_api.complete_class_session(ctx["session"]["id"], PC))
    contract = get_contract(ctx["contract"]["id"])
    assert contract["settlement_headcount"] == 1
    assert contract["settlement_amount_cents"] == 5000


def test_settlement_excludes_dropped_registrations(api):
    """PRD §3.9: "Under `ENROLLMENT_BASIS`, every registration still
    `ENROLLED` at completion counts."

    Design: Corner/calculations/settlement_excludes_dropped_registrations
    """
    catalog = setup_multi_session_catalog([
        {"title": "Rowing", "fee_resident_cents": 10000, "fee_nonresident_cents": 10000,
         "contract_overrides": {"settlement_basis": "ENROLLMENT_BASIS"}},
    ])
    ctx = {"season": catalog["season"], **catalog["sessions"][0]}
    household_1, parts_1 = setup_household_with_participants(count=1, account_name="H1")
    household_2, parts_2 = setup_household_with_participants(count=1, account_name="H2")
    r1 = register_and_pay(ctx["session"]["id"], parts_1[0]["id"], household_1["id"])
    register_and_pay(ctx["session"]["id"], parts_2[0]["id"], household_2["id"])

    # Dropped before the first meeting: excluded from the counted set.
    drop_registration(r1["id"], household_1["id"])

    set_clock(ctx["session"]["enrollment_check_at"])
    run_sweep(catalog["season"]["id"])
    set_clock(AFTER_ALL_MEETINGS)
    validate_success(_api.complete_class_session(ctx["session"]["id"], PC))

    contract = get_contract(ctx["contract"]["id"])
    assert contract["settlement_headcount"] == 1     # only the survivor counts
    assert contract["settlement_amount_cents"] == 5000


def test_instructor_cannot_accept_others_contract(api):
    """PRD §3.3: "The named instructor — and only that instructor, by
    entity-backed identity — may accept it, moving it to `ACCEPTED`, provided
    the session is still `DRAFT` or `PUBLISHED`; accepting under any other
    session state is `ERR_INVALID_STATE`, and a different instructor
    attempting the accept is `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/instructor_cannot_accept_others_contract
    """
    season = create_published_season()
    program = create_program(season["id"], name="Archery", category="Sports")
    instructor_1 = create_instructor(full_name="Arch A", email="aa2@x.com")
    instructor_2 = create_instructor(full_name="Arch B", email="ab2@x.com")
    session = create_class_session(program["id"], instructor_1["id"], title="SI")
    contract = create_contract(session["id"], instructor_1["id"])

    resp = _api.accept_instructor_contract(
        contract["id"], make_instructor_headers(instructor_2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    accepted = validate_success(_api.accept_instructor_contract(
        contract["id"], make_instructor_headers(instructor_1["id"])))
    assert accepted["status"] == "ACCEPTED"
