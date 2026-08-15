"""Enrollment, tuition assessment, and account/ledger derivation claims
(PRD §3.2, §2.5, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    create_enrollment_payload,
    enroll,
    entries_of_type,
    find_charge_entry,
    make_student,
    make_student_headers,
    read_account,
    set_clock,
    setup_account_with_enrollment,
    setup_term_with_rate,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_enrollment_system_fields_server_minted(api, bursar_staff_headers):
    """PRD §3.2: "On acceptance the system get-or-creates the `StudentAccount`
    for that student and term — exactly one account ever exists per
    student-term pair — and immediately runs the tuition assessment." and "An
    enrollment is born in status `ENROLLED` with `exit_date` null", and "The
    enrollment records the combined tuition-plus-fee total as its
    `assessed_total_cents`".

    Design: Corner/entities/enrollment_system_fields_server_minted
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-SYS")
    enrollment = ctx["enrollment"]
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["exit_date"] is None
    # 12 credits engages the flat rate: 420000 tuition + 15000 flat fee.
    assert enrollment["assessed_total_cents"] == 435000
    # The get-or-created account is a real StudentAccount for this pair.
    account = validate_success(
        api.get_account(enrollment["account_id"], bursar_staff_headers), 200
    )
    assert account["student_id"] == ctx["student"]["id"]
    assert account["term_id"] == ctx["term"]["id"]


def test_ledger_entry_immutability(api, bursar_staff_headers):
    """PRD §3.2: "The assessment posts **two** ledger entries to the account:
    a `CHARGE` with `charge_kind` `TUITION` carrying the tuition amount, and a
    second `CHARGE` with `charge_kind` `FEE` carrying the flat fee. Both
    entries are dated with `due_date` equal to the term's `census_date`".
    PRD §2.5: "Ledger entries expose only `id` and `created_at` as common
    properties; because they are immutable once posted, they carry neither
    `updated_at` nor a `version` counter."

    Design: Corner/entities/ledger_entry_immutability
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-LED")
    ledger, _meta = validate_paginated(
        api.get_account_ledger(ctx["account_id"], bursar_staff_headers)
    )
    assert len(ledger) == 2, f"assessment posts exactly 2 entries, got {len(ledger)}"
    tuition = find_charge_entry(ledger, "TUITION")
    fee = find_charge_entry(ledger, "FEE")
    assert tuition["amount_cents"] == 35000
    assert fee["amount_cents"] == 15000
    for entry in ledger:
        assert_ledger_entry(entry)
        assert entry["due_date"] == "2026-09-07", (
            "assessment charges are due on the term census_date"
        )
        assert entry["enrollment_id"] == ctx["enrollment"]["id"]


def test_account_computed_buckets(api, bursar_staff_headers):
    """PRD §2.5: "Then `balance_cents` is derived as `charges_total_cents`
    minus `payments_total_cents` minus `waivers_total_cents` minus
    `sponsor_total_cents` minus `writeoffs_total_cents` minus the
    refund-payouts sum."
    PRD §2.6: "Under normal rules, `past_due_cents` is the signed sum over
    charge-family entries whose `due_date` falls strictly before the current
    clock date, floored at zero."

    Design: Corner/entities/account_computed_buckets
    """
    ctx = setup_account_with_enrollment(credit_hours=12, external_ref="S-BUK")
    account = validate_success(
        api.get_account(ctx["account_id"], bursar_staff_headers), 200
    )
    assert account["charges_total_cents"] == 435000
    assert account["balance_cents"] == 435000
    assert account["payments_total_cents"] == 0
    assert account["waivers_total_cents"] == 0
    assert account["sponsor_total_cents"] == 0
    assert account["writeoffs_total_cents"] == 0
    # Clock is the startup default 2026-08-01, before the 2026-09-07 due date.
    assert account["past_due_cents"] == 0
    assert account["status"] == "OPEN"


def test_enrollment_default_effective_date(api, registrar_headers):
    """PRD §3.2: "when the effective date is omitted it defaults to the current
    clock date".
    PRD §2.4: "the logical clock reads exactly `2026-08-01T00:00:00Z`; it never
    silently falls back to wall-clock time."

    Design: Corner/entities/enrollment_default_effective_date
    """
    term, _rate = setup_term_with_rate()
    student = make_student("S-DEF", "Default Date")
    set_clock("2026-08-26T00:00:00Z")
    payload = create_enrollment_payload(student["id"], term["id"], credit_hours=3)
    del payload["effective_date"]
    enrollment = validate_success(
        api.create_enrollment(payload, registrar_headers), 201
    )
    assert enrollment["effective_date"] == "2026-08-26", (
        "omitted effective_date must default to the logical clock date"
    )


@pytest.mark.parametrize("bad_hours", [0, 25])
def test_credit_hours_out_of_range_returns_422(
    api, registrar_headers, bad_hours
):
    """PRD §3.2: "Credit hours must be an integer from 1 to 24 inclusive;
    anything outside that range is rejected with `ERR_CREDIT_HOURS_INVALID`
    (HTTP 422)."

    Design: Corner/validations/credit_hours_zero_returns_422
    """
    term, _rate = setup_term_with_rate()
    student = make_student("S-ZC", "Zero Cr")
    res = api.create_enrollment(
        create_enrollment_payload(student["id"], term["id"],
                                  credit_hours=bad_hours),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_HOURS_INVALID, expected_status=422)


def test_no_applicable_rate_returns_422(api, registrar_headers):
    """PRD §3.2: "Assessment locates the single rate card whose term matches,
    whose `residency` equals the student's `residency_status`, whose `level`
    equals the student's `level`, and whose closed effective window contains
    the enrollment's `effective_date`; if no such rate card exists, enrollment
    fails with `ERR_NO_APPLICABLE_TUITION_RATE` (HTTP 422)."

    Design: Corner/validations/no_applicable_rate_returns_422
    """
    term, _rate = setup_term_with_rate()  # card covers UNDERGRADUATE only
    grad = make_student("S-GRD", "Grad", level="GRADUATE")
    res = api.create_enrollment(
        create_enrollment_payload(grad["id"], term["id"], credit_hours=6),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_APPLICABLE_TUITION_RATE, expected_status=422)


def test_reverse_reachability_sublists(api, bursar_staff_headers):
    """PRD §3.2: "A student's accounts, an individual account with all of its
    computed bucket totals, and the account's append-only ledger can each be
    read back ... Enrollment listings support filtering by `student_id`,
    `term_id`, `account_id`, and `status`."

    Design: Corner/endpoints/reverse_reachability_sublists
    """
    ctx = setup_account_with_enrollment(credit_hours=3, external_ref="S-RCH")
    sid = ctx["student"]["id"]
    tid = ctx["term"]["id"]
    acc = ctx["account_id"]

    student_accounts = validate_success(
        api.list_student_accounts(sid, bursar_staff_headers), 200
    )
    assert [a["id"] for a in student_accounts] == [acc]

    term_accounts = validate_success(
        api.list_term_accounts(tid, bursar_staff_headers), 200
    )
    assert acc in [a["id"] for a in term_accounts]

    ledger, _m = validate_paginated(
        api.get_account_ledger(acc, bursar_staff_headers)
    )
    assert len(ledger) == 2
    assert find_charge_entry(ledger, "TUITION")["amount_cents"] == 105000
    assert find_charge_entry(ledger, "FEE")["amount_cents"] == 15000

    enrollments, _m2 = validate_paginated(
        api.list_enrollments(
            bursar_staff_headers, params={"student_id": sid, "term_id": tid}
        )
    )
    assert [e["id"] for e in enrollments] == [ctx["enrollment"]["id"]]


def test_student_cannot_read_other_account(api, bursar_staff_headers):
    """PRD §2.1: "a student caller may only touch resources whose owning
    `Student.id` equals their `X-User-ID`", and a failed ownership check "is
    rejected with `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/student_cannot_read_other_account
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-OA")
    intruder = make_student("S-IB", "Intruder B")
    acc = ctx["account_id"]

    res = api.get_account(acc, make_student_headers(intruder["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    own = validate_success(
        api.get_account(acc, make_student_headers(ctx["student"]["id"])), 200
    )
    assert own["balance_cents"] == 50000


class TestFullTimeCreditThreshold:
    """The flat-rate branch engages AT full_time_threshold_credits (PRD §3.2)."""

    def test_below_threshold_prices_per_credit(self, api):
        """PRD §3.2: "Below the full-time threshold, tuition is simply the
        `credit_hours` multiplied by the `per_credit_rate_cents`. The mandatory
        term `flat_fee_cents` is then added."

        Design: Difficulty/boundary_precision_check/full_time_credit_threshold
        """
        term, _rate = setup_term_with_rate()
        student = make_student("S-H1", "Half")
        enrollment = enroll(student["id"], term["id"], credit_hours=11)
        # 11 x 35000 + 15000 flat fee.
        assert enrollment["assessed_total_cents"] == 400000

    def test_at_threshold_engages_flat_rate(self, api):
        """PRD §3.2: "When the student's `credit_hours` meet or exceed the
        rate's `full_time_threshold_credits`, the tuition component is the
        rate's `flat_rate_cents` plus, for each credit hour above the rate's
        `max_flat_credits`, the `overload_rate_cents` per extra hour."

        Design: Difficulty/boundary_precision_check/full_time_credit_threshold
        """
        term, _rate = setup_term_with_rate()
        student = make_student("S-F1", "Full")
        enrollment = enroll(student["id"], term["id"], credit_hours=12)
        # Flat 420000 + 15000 fee; the >= comparison engages at exactly 12.
        assert enrollment["assessed_total_cents"] == 435000


class TestTuitionFlatThresholdOverload:
    """Three-branch interaction of the tiered pricing ladder (PRD §3.2)."""

    def test_per_credit_flat_and_overload_branch_amounts(self, api):
        """PRD §3.2: "When the student's `credit_hours` meet or exceed the
        rate's `full_time_threshold_credits`, the tuition component is the
        rate's `flat_rate_cents` plus, for each credit hour above the rate's
        `max_flat_credits`, the `overload_rate_cents` per extra hour. Below the
        full-time threshold, tuition is simply the `credit_hours` multiplied by
        the `per_credit_rate_cents`."

        Design: Difficulty/combinatorial_formula/tuition_flat_threshold_overload
        """
        term, _rate = setup_term_with_rate()
        s11 = make_student("S-11", "Eleven")
        s12 = make_student("S-12", "Twelve")
        s20 = make_student("S-20", "Twenty")
        e11 = enroll(s11["id"], term["id"], credit_hours=11)
        e12 = enroll(s12["id"], term["id"], credit_hours=12)
        e20 = enroll(s20["id"], term["id"], credit_hours=20)
        assert e11["assessed_total_cents"] == 400000, "11cr: 11x35000 + 15000"
        assert e12["assessed_total_cents"] == 435000, "12cr: 420000 + 15000"
        # 20cr: flat 420000 + (20-18) x 35000 overload + 15000 fee.
        assert e20["assessed_total_cents"] == 505000

    def test_overload_enrollment_posts_tuition_and_fee_charges(
        self, api, bursar_staff_headers
    ):
        """PRD §3.2: "The assessment posts **two** ledger entries to the
        account: a `CHARGE` with `charge_kind` `TUITION` carrying the tuition
        amount, and a second `CHARGE` with `charge_kind` `FEE` carrying the
        flat fee."

        Design: Difficulty/combinatorial_formula/tuition_flat_threshold_overload
        """
        ctx = setup_account_with_enrollment(credit_hours=20, external_ref="S-OVL")
        ledger, _m = validate_paginated(
            api.get_account_ledger(ctx["account_id"], bursar_staff_headers)
        )
        charges = entries_of_type(ledger, "CHARGE")
        assert len(charges) == 2
        # Tuition component is 420000 flat + 2 x 35000 overload = 490000.
        assert find_charge_entry(ledger, "TUITION")["amount_cents"] == 490000
        assert find_charge_entry(ledger, "FEE")["amount_cents"] == 15000
        account = read_account(ctx["account_id"])
        assert account["charges_total_cents"] == 505000
