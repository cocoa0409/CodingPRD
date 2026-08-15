"""Co-op cascades: rejection-driven and cancellation-driven drops, refund
waterfall tiers, waitlist promotion order, ledger settlement, OCC, and the
safety-vs-fiscal gate ordering."""
from test_helpers import (
    REMEDIATION_SCORES,
    ApiErrorId,
    assert_coop_enrollment,
    create_open_coop_class,
    create_open_year,
    create_submitted_portfolio,
    evaluate_portfolio,
    get_ledger,
    get_success_data,
    register_coop,
    register_coop_ok,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def _three_family_class(api, capacity, title="Co-op Class"):
    """Year + three ACTIVE enrollments in distinct families + one OPEN class."""
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam A",
                                    district_code="D-17")
    ctx_b = setup_active_enrollment(year["id"], 5, family_name="Fam B",
                                    district_code="D-18", student_name="Kid B",
                                    date_of_birth="2015-02-02")
    ctx_c = setup_active_enrollment(year["id"], 6, family_name="Fam C",
                                    district_code="D-19", student_name="Kid C",
                                    date_of_birth="2014-03-03")
    coop_class = create_open_coop_class(year["id"], title=title, capacity=capacity)
    return year, ctx_a, ctx_b, ctx_c, coop_class


def _remediate_thrice(api, portfolio_id, parent_headers):
    """Drive a portfolio through two remediation cycles to the third submission."""
    get_success_data(evaluate_portfolio(portfolio_id, "REMEDIATION_REQUIRED",
                                        subject_scores=REMEDIATION_SCORES))
    get_success_data(api.submit_portfolio(portfolio_id, parent_headers))
    get_success_data(evaluate_portfolio(portfolio_id, "REMEDIATION_REQUIRED",
                                        subject_scores=REMEDIATION_SCORES))
    get_success_data(api.submit_portfolio(portfolio_id, parent_headers))


def _setup_rejection_cascade(api):
    """A CONFIRMED at capacity 1, B WAITLISTED; A's portfolio at attempt 3."""
    year, ctx_a, ctx_b, _ctx_c, coop_class = _three_family_class(api, 1, title="Chess Club")
    ce_a = register_coop_ok(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])
    ce_b = register_coop_ok(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])
    assert ce_b["status"] == "WAITLISTED"
    portfolio = create_submitted_portfolio(ctx_a["enrollment"], ctx_a["family"])
    _remediate_thrice(api, portfolio["id"], ctx_a["parent_headers"])
    return ctx_a, ctx_b, coop_class, ce_a, ce_b, portfolio


def test_portfolio_rejection_cascade_drops_confirmed_with_full_refund(api):
    """PRD §3.5: "A finally or forcibly rejected portfolio drives the
    enrollment's `compliance_standing` to `NONCOMPLIANT`, firing the standing
    cascade of §3.7 — confirmed co-op enrollments dropped with full
    `SCHOOL_STANDING` refunds, waitlisted ones cancelled, freed seats offered to
    the waitlist."
    PRD §3.7: "By contrast, school-initiated losses — a class cancellation
    (`SCHOOL_CANCEL`) or a standing-driven drop (`SCHOOL_STANDING`) — always
    refund the full `fee_cents`, materials included, with no administrative fee."

    Design: Difficulty/transitive_cascade/portfolio_rejection_noncompliance_coop_cascade
    """
    ctx_a, _ctx_b, _cls, ce_a, _ce_b, portfolio = _setup_rejection_cascade(api)

    # Third remediation at attempt_count 3 forces rejection -> NONCOMPLIANT.
    get_success_data(evaluate_portfolio(portfolio["id"], "REMEDIATION_REQUIRED",
                                        subject_scores=REMEDIATION_SCORES))

    portfolio_after = validate_success(api.get_portfolio(portfolio["id"], REGISTRAR))
    assert portfolio_after["status"] == "REJECTED"
    enrollment = validate_success(api.get_enrollment(ctx_a["enrollment"]["id"], REGISTRAR))
    assert enrollment["compliance_standing"] == "NONCOMPLIANT"

    ce_a_after = validate_success(api.get_coop_enrollment(ce_a["id"], REGISTRAR))
    assert ce_a_after["status"] == "DROPPED"
    assert ce_a_after["drop_reason"] == "SCHOOL_STANDING"
    assert ce_a_after["refund_cents"] == 11000, "standing drop refunds 100%"
    ledger_a = get_ledger(ctx_a["family"]["id"])
    assert ledger_a["fee_balance_cents"] == 0, "11000 charge - 11000 refund"


def test_portfolio_rejection_cascade_promotes_waitlisted(api):
    """PRD §3.7: "Waitlist promotion is deterministic. Candidates are the
    class's `WAITLISTED` enrollments whose underlying enrollment is still
    `ACTIVE`, whose standing is not `NONCOMPLIANT`, whose grade falls within the
    class's band, and whose weekly window does not overlap the student's other
    `CONFIRMED` classes."
    PRD §3.7: "Promotion stamps `promoted_at`, computes the fee using the co-op
    enrollment's original creation time for early-bird eligibility, debits the
    family ledger, and increments the class's `seats_taken` and `version`."

    Design: Difficulty/transitive_cascade/portfolio_rejection_noncompliance_coop_cascade
    """
    ctx_a, ctx_b, coop_class, _ce_a, ce_b, portfolio = _setup_rejection_cascade(api)
    get_success_data(evaluate_portfolio(portfolio["id"], "REMEDIATION_REQUIRED",
                                        subject_scores=REMEDIATION_SCORES))

    ce_b_after = validate_success(api.get_coop_enrollment(ce_b["id"], REGISTRAR))
    assert_coop_enrollment(ce_b_after)
    assert ce_b_after["status"] == "CONFIRMED", "promoted from WAITLISTED"
    assert ce_b_after["promoted_at"] is not None
    assert ce_b_after["fee_cents"] == 11000, "no early-bird, no sibling at promotion"
    ledger_b = get_ledger(ctx_b["family"]["id"])
    assert ledger_b["fee_balance_cents"] == 11000
    coop_after = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert coop_after["seats_taken"] == 1, "A's seat released, B's seat taken"


def _setup_cancel_cascade(api):
    """A and B CONFIRMED at capacity 2; C WAITLISTED."""
    year, ctx_a, ctx_b, ctx_c, coop_class = _three_family_class(api, 2, title="Robotics Lab")
    ce_a = register_coop_ok(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])
    ce_b = register_coop_ok(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])
    ce_c = register_coop_ok(coop_class["id"], ctx_c["enrollment"]["id"], ctx_c["family"]["id"])
    assert ce_c["status"] == "WAITLISTED"
    return ctx_a, ctx_b, ctx_c, coop_class, ce_a, ce_b, ce_c


def test_class_cancellation_drops_confirmed_with_full_refunds(api):
    """PRD §3.7: "cancellation drops every `CONFIRMED` enrollment with
    `drop_reason` `SCHOOL_CANCEL` and a full refund — `refund_cents` equal to the
    entire `fee_cents`, no administrative fee, materials included — crediting
    each family ledger, cancels every `WAITLISTED` enrollment (which was never
    charged), recomputes `seats_taken` to zero, and increments the class's
    `version`."
    PRD §3.7: "whenever a refund or payment returns the balance to exactly zero,
    `oldest_unpaid_charge_at` clears to null."

    Design: Difficulty/transitive_cascade/class_cancellation_refund_cascade
    """
    ctx_a, ctx_b, _ctx_c, coop_class, ce_a, ce_b, _ce_c = _setup_cancel_cascade(api)
    cancelled = validate_success(api.cancel_coop_class(coop_class["id"], REGISTRAR))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_taken"] == 0

    for ce in (ce_a, ce_b):
        after = validate_success(api.get_coop_enrollment(ce["id"], REGISTRAR))
        assert after["status"] == "DROPPED"
        assert after["drop_reason"] == "SCHOOL_CANCEL"
        assert after["refund_cents"] == 11000

    ledger_a = get_ledger(ctx_a["family"]["id"])
    assert ledger_a["fee_balance_cents"] == 0
    assert ledger_a["oldest_unpaid_charge_at"] is None


def test_class_cancellation_cancels_waitlisted_without_charge(api):
    """PRD §3.7: "cancels every `WAITLISTED` enrollment (which was never
    charged), recomputes `seats_taken` to zero, and increments the class's
    `version`."

    Design: Difficulty/transitive_cascade/class_cancellation_refund_cascade
    """
    _ctx_a, _ctx_b, ctx_c, coop_class, _ce_a, _ce_b, ce_c = _setup_cancel_cascade(api)
    get_success_data(api.cancel_coop_class(coop_class["id"], REGISTRAR))

    ce_c_after = validate_success(api.get_coop_enrollment(ce_c["id"], REGISTRAR))
    assert ce_c_after["status"] == "CANCELLED", "waitlisted: no charge, no refund"
    ledger_c = get_ledger(ctx_c["family"]["id"])
    assert ledger_c["fee_balance_cents"] == 0, "never charged"


def test_coop_confirm_drop_roundtrip_seat_invariant(api):
    """PRD §3.7: "Any drop credits the family ledger by `refund_cents`,
    decrements `seats_taken` by one, increments the class's `version`, and runs
    waitlist promotion against the freed seat."
    PRD §3.7: "Confirmation moves money: the family's `fee_balance_cents` is
    debited by the line's `fee_cents`, the class's `seats_taken` increments, and
    the class's `version` increments."

    Design: Difficulty/compensating_invariant/coop_confirm_drop_roundtrip_invariant
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Inv",
                                  district_code="D-24", date_of_birth="2016-12-12")
    coop_class = create_open_coop_class(year["id"], title="Choir", meeting_day="TUE",
                                        capacity=2)
    assert coop_class["seats_taken"] == 0

    ce = register_coop_ok(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    mid = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert mid["seats_taken"] == 1

    get_success_data(api.drop_coop_enrollment(ce["id"], ctx["parent_headers"]))
    after = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert after["seats_taken"] == 0, "seat inventory restored to its prior value"


def test_coop_confirm_drop_roundtrip_money_drift_is_admin_fee(api):
    """PRD §3.7: "A parent may drop a confirmed seat; the enrollment moves
    `CONFIRMED` → `DROPPED` with `drop_reason` `PARENT_INITIATED`, and the
    refund waterfall determines `refund_cents`: dropping before the class's
    start date refunds the line total minus a 2,500-cent administrative fee,
    floored at zero; dropping within fourteen days after the start date refunds
    half of the line total above the materials fee, rounded half-up; dropping
    later refunds nothing."

    Design: Difficulty/compensating_invariant/coop_confirm_drop_roundtrip_invariant
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Inv",
                                  district_code="D-24", date_of_birth="2016-12-12")
    # Start 2026-08-25, registration at the 2026-08-01 default clock: pre-start.
    coop_class = create_open_coop_class(year["id"], title="Choir", meeting_day="TUE",
                                        capacity=2)
    ce = register_coop_ok(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    assert ce["fee_cents"] == 11000

    dropped = validate_success(api.drop_coop_enrollment(ce["id"], ctx["parent_headers"]))
    assert dropped["status"] == "DROPPED"
    assert dropped["drop_reason"] == "PARENT_INITIATED"
    assert dropped["refund_cents"] == 8500, "11000 - 2500 administrative fee"
    ledger = get_ledger(ctx["family"]["id"])
    assert ledger["fee_balance_cents"] == 2500, "the administrative fee is the only drift"


def test_refund_waterfall_partial_and_zero_tiers(api):
    """PRD §3.7: "dropping before the class's start date refunds the line total
    minus a 2,500-cent administrative fee, floored at zero; dropping within
    fourteen days after the start date refunds half of the line total above the
    materials fee, rounded half-up; dropping later refunds nothing."

    Design: Corner/calculations/refund_waterfall_partial_and_zero_tiers
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam PA",
                                    district_code="D-46")
    ctx_b = setup_active_enrollment(year["id"], 4, family_name="Fam PB",
                                    district_code="D-47", student_name="Kid PB",
                                    date_of_birth="2016-02-02")
    coop_class = create_open_coop_class(year["id"], title="Waterfall",
                                        meeting_day="WED", capacity=5)
    ce_a = register_coop_ok(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])
    ce_b = register_coop_ok(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])

    # A drops at 2026-08-30: start (2026-08-25) <= now < start + 14 days.
    set_clock("2026-08-30T00:00:00Z")
    dropped_a = validate_success(api.drop_coop_enrollment(ce_a["id"], ctx_a["parent_headers"]))
    assert dropped_a["drop_reason"] == "PARENT_INITIATED"
    assert dropped_a["refund_cents"] == 5000, "round_half_up((11000 - 1000) * 0.50)"
    assert get_ledger(ctx_a["family"]["id"])["fee_balance_cents"] == 6000

    # B drops at 2026-09-10: at/after start + 14 days (2026-09-08).
    set_clock("2026-09-10T00:00:00Z")
    dropped_b = validate_success(api.drop_coop_enrollment(ce_b["id"], ctx_b["parent_headers"]))
    assert dropped_b["refund_cents"] == 0
    assert get_ledger(ctx_b["family"]["id"])["fee_balance_cents"] == 11000


def test_waitlist_promotion_order_deterministic(api):
    """PRD §3.7: "They are ranked by the co-op enrollment's own creation time,
    earliest first, with ties broken by the candidate enrollment's creation
    time, earliest first — identifiers are never consulted. Exactly one
    candidate is promoted per freed seat, and the selection re-runs after each
    promotion while seats remain; an empty candidate set is a no-op."

    Design: Corner/endpoints/waitlist_promotion_order_deterministic
    """
    year, ctx_a, ctx_b, ctx_c, coop_class = _three_family_class(api, 1, title="Tiny")
    ce_a = register_coop_ok(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])
    set_clock("2026-08-01T00:00:01Z")
    ce_b = register_coop_ok(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])
    set_clock("2026-08-01T00:00:02Z")
    ce_c = register_coop_ok(coop_class["id"], ctx_c["enrollment"]["id"], ctx_c["family"]["id"])
    assert ce_b["status"] == "WAITLISTED"
    assert ce_c["status"] == "WAITLISTED"

    dropped = validate_success(api.drop_coop_enrollment(ce_a["id"], ctx_a["parent_headers"]))
    assert dropped["refund_cents"] == 8500, "pre-start parent drop: 11000 - 2500"

    ce_b_after = validate_success(api.get_coop_enrollment(ce_b["id"], REGISTRAR))
    assert ce_b_after["status"] == "CONFIRMED", "earlier created_at (00:00:01) wins"
    assert ce_b_after["promoted_at"] is not None
    assert ce_b_after["fee_cents"] == 11000

    ce_c_after = validate_success(api.get_coop_enrollment(ce_c["id"], REGISTRAR))
    assert ce_c_after["status"] == "WAITLISTED"
    assert ce_c_after["promoted_at"] is None

    coop_after = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert coop_after["seats_taken"] == 1, "one promotion per freed seat"


def test_ledger_payment_settles_balance(api):
    """PRD §3.7: "Families settle up through ledger payments — a parent paying
    against their own family, or a registrar recording one — with an
    `amount_cents` that subtracts from the balance, clears
    `oldest_unpaid_charge_at` if the balance lands exactly on zero, recomputes
    `fee_status`, and increments the family's `version`."
    PRD §3.7: "The family's `fee_status` is `OVERDUE` when a positive balance
    has aged more than thirty days past `oldest_unpaid_charge_at`, and `CURRENT`
    otherwise."

    Design: Corner/endpoints/ledger_payment_settles_balance
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Pay",
                                  district_code="D-63")
    coop_class = create_open_coop_class(year["id"], title="Payclass", meeting_day="THU")
    register_coop_ok(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    set_clock("2026-09-05T00:00:00Z")

    pre = get_ledger(ctx["family"]["id"])
    assert pre["fee_balance_cents"] == 11000
    assert pre["fee_status"] == "OVERDUE", "2026-09-05 is more than 30 days past 2026-08-01"

    paid = validate_success(
        api.create_ledger_payment(ctx["family"]["id"], {"amount_cents": 11000},
                                  ctx["parent_headers"]),
        201,
    )
    assert paid["fee_balance_cents"] == 0
    post = get_ledger(ctx["family"]["id"])
    assert post["fee_balance_cents"] == 0
    assert post["oldest_unpaid_charge_at"] is None
    assert post["fee_status"] == "CURRENT"


def _setup_overdue_family(api):
    """Family charged 11000 (class start 2026-08-25, registered at the default
    clock), then clock advanced past the 30-day grace -> OVERDUE."""
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Fo",
                                  district_code="D-78")
    class1 = create_open_coop_class(year["id"], title="Cls1")
    register_coop_ok(class1["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    set_clock("2026-09-05T00:00:00Z")
    return year, ctx


def test_fees_overdue_blocks_registration(api):
    """PRD §3.7: "a family whose `fee_status` is `OVERDUE` may not take on new
    charges, refused with `ERR_FEES_OVERDUE`."

    Design: Corner/errors/fees_overdue_blocks_registration
    """
    year, ctx = _setup_overdue_family(api)
    ledger = get_ledger(ctx["family"]["id"])
    assert ledger["fee_balance_cents"] == 11000
    assert ledger["fee_status"] == "OVERDUE"

    class2 = create_open_coop_class(
        year["id"], title="Cls2", subject="Music", meeting_day="WED",
        meeting_start_minutes=600, meeting_end_minutes=700,
        start_date="2026-10-01", end_date="2027-01-15",
        fee_base_cents=5000, materials_fee_cents=0,
    )
    resp = register_coop(class2["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_FEES_OVERDUE)
    class2_after = get_success_data(api.get_coop_class(class2["id"], REGISTRAR))
    assert class2_after["seats_taken"] == 0


def _setup_safety_and_fiscal_failure(api):
    """Enrollment NONCOMPLIANT (locked) AND family OVERDUE (2500 aged balance);
    a second OPEN class ready to register. Returns (year, ctx, class2)."""
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Gate",
                                  district_code="D-15", date_of_birth="2016-05-05")
    # Charge 11000, then drop pre-start (class start 2026-08-25 > 2026-08-01):
    # refund 11000 - 2500 = 8500, leaving a 2500 balance stamped at 2026-08-01.
    class1 = create_open_coop_class(year["id"], title="Class One")
    ce1 = register_coop_ok(class1["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    dropped = get_success_data(api.drop_coop_enrollment(ce1["id"], ctx["parent_headers"]))
    assert dropped["refund_cents"] == 8500

    set_clock("2026-09-05T00:00:00Z")
    # No active co-op enrollments exist now, so the override cascade is a no-op
    # and the 2500 balance survives.
    get_success_data(
        api.create_standing_override(
            ctx["enrollment"]["id"],
            {"standing": "NONCOMPLIANT", "reason": "director audit hold"},
            DIRECTOR,
        )
    )
    class2 = create_open_coop_class(
        year["id"], title="Class Two", subject="Music", meeting_day="WED",
        meeting_start_minutes=600, meeting_end_minutes=700,
        start_date="2026-10-01", end_date="2027-01-15",
        fee_base_cents=5000, materials_fee_cents=0,
    )
    return year, ctx, class2


def test_coop_registration_safety_precedes_fiscal_gate(api):
    """PRD §2.8: "Every request is evaluated against a fixed pipeline of checks,
    and the order is part of the contract — when several problems coexist, the
    earliest check in the pipeline determines the error the caller sees."
    PRD §2.8: "Fiscal gates, always last: `ERR_FEES_OVERDUE` and
    `ERR_FEES_UNSETTLED`."
    PRD §3.7: "a `NONCOMPLIANT` enrollment is refused with
    `ERR_ENROLLMENT_NONCOMPLIANT`; and a family whose `fee_status` is `OVERDUE`
    may not take on new charges, refused with `ERR_FEES_OVERDUE`."

    Design: Difficulty/priority_pair_validation_conflict/coop_registration_safety_before_fiscal_priority
    """
    _year, ctx, class2 = _setup_safety_and_fiscal_failure(api)
    ledger = get_ledger(ctx["family"]["id"])
    assert ledger["fee_balance_cents"] == 2500
    assert ledger["fee_status"] == "OVERDUE", "2026-09-05 > 2026-08-01 + 30 days"

    # Both the standing gate and the fiscal gate fail; the earlier (standing)
    # check in the pipeline determines the reported error.
    resp = register_coop(class2["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NONCOMPLIANT)


def test_coop_registration_dual_failure_leaves_ledger_unchanged(api):
    """PRD §3.7: "a `NONCOMPLIANT` enrollment is refused with
    `ERR_ENROLLMENT_NONCOMPLIANT`; and a family whose `fee_status` is `OVERDUE`
    may not take on new charges, refused with `ERR_FEES_OVERDUE`."
    PRD §2.8: "Every request is evaluated against a fixed pipeline of checks,
    and the order is part of the contract — when several problems coexist, the
    earliest check in the pipeline determines the error the caller sees."

    Design: Difficulty/priority_pair_validation_conflict/coop_registration_safety_before_fiscal_priority
    """
    _year, ctx, class2 = _setup_safety_and_fiscal_failure(api)
    resp = register_coop(class2["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NONCOMPLIANT)

    after = get_ledger(ctx["family"]["id"])
    assert after["fee_balance_cents"] == 2500, "no new charge was created"
    assert after["fee_status"] == "OVERDUE"
    class2_after = get_success_data(api.get_coop_class(class2["id"], REGISTRAR))
    assert class2_after["seats_taken"] == 0


def test_occ_stale_version_coop_registration(api):
    """PRD §2.7: "Creating a co-op enrollment — the operation that registers a
    student into a co-op class — requires the request body to carry
    `expected_coop_class_version`, the client-side observation of the class's
    current `version`. Because every successful registration mutates the class's
    `seats_taken`, a client deciding between a confirmed seat and a waitlist
    position from an outdated seat count would act on fiction; if
    `expected_coop_class_version` does not match the class's current `version`,
    the registration is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_coop_registration
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam Oa",
                                    district_code="D-81")
    ctx_b = setup_active_enrollment(year["id"], 4, family_name="Fam Ob",
                                    district_code="D-82", student_name="Kid Ob",
                                    date_of_birth="2016-02-02")
    coop_class = create_open_coop_class(year["id"], title="OccClass",
                                        meeting_day="TUE",
                                        meeting_start_minutes=540,
                                        meeting_end_minutes=600, capacity=10,
                                        fee_base_cents=1000, materials_fee_cents=0)
    stale_version = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))["version"]

    # A registers with the fresh version; that registration bumps it.
    ce_a = validate_success(
        api.create_coop_enrollment(
            coop_class["id"],
            {"enrollment_id": ctx_a["enrollment"]["id"],
             "expected_coop_class_version": stale_version},
            ctx_a["parent_headers"],
        ),
        201,
    )
    assert ce_a["status"] == "CONFIRMED"

    # B replays the stale version even though capacity remains.
    resp = api.create_coop_enrollment(
        coop_class["id"],
        {"enrollment_id": ctx_b["enrollment"]["id"],
         "expected_coop_class_version": stale_version},
        ctx_b["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # B re-reads and succeeds on the fresh version.
    fresh_version = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))["version"]
    ce_b = validate_success(
        api.create_coop_enrollment(
            coop_class["id"],
            {"enrollment_id": ctx_b["enrollment"]["id"],
             "expected_coop_class_version": fresh_version},
            ctx_b["parent_headers"],
        ),
        201,
    )
    assert ce_b["status"] == "CONFIRMED"
    final = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert final["seats_taken"] == 2
