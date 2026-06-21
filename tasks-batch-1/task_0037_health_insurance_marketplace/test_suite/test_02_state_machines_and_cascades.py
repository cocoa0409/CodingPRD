"""Non-linear state machines, parallel dimensions, and transitive cascades (queue A)."""
from test_helpers import (
    validate_success,
    setup_determined_application,
    setup_enrollment,
    create_household_with_primary,
    add_member,
    make_applicant_headers,
)


def test_reopen_reverts_determined_application_to_draft(api):
    """PRD §3.3: "an application that is currently `DETERMINED` and that has no enrollment yet may be reverted from `DETERMINED` back to `DRAFT`. Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`."

    Design: Difficulty/non_linear_state_machine/application_determined_reverts_to_draft_on_reopen
    """
    ctx = setup_determined_application("app-5", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-5")
    reopened = validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    assert reopened["status"] == "DRAFT"
    assert reopened["submitted_at"] is None
    dets = validate_success(api.get_determination(ctx["application"]["id"], h), 200)
    assert isinstance(dets, list) and len(dets) == 0


def test_reopen_increments_application_version(api):
    """PRD §3.3: "Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`."

    Design: Difficulty/non_linear_state_machine/application_determined_reverts_to_draft_on_reopen
    """
    ctx = setup_determined_application("app-5b", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-5b")
    before = validate_success(api.get_application(ctx["application"]["id"], h), 200)["version"]
    reopened = validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    assert reopened["version"] == before + 1
    assert reopened["status"] == "DRAFT"


def test_pay_binder_advances_payment_dimension_only(api):
    """PRD §3.6: "The applicant pays the binder, moving the enrollment from `AWAITING_BINDER` to `PAID`; this transition is permitted only while `payment_status` is `AWAITING_BINDER`."
    PRD §3.6: "An enrollment carries two independent state dimensions that evolve
    separately."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_payment_and_lifecycle_dimensions
    """
    ctx = setup_enrollment("app-6", income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                           benchmark_gross=50_000)
    h = make_applicant_headers("app-6")
    paid = validate_success(api.pay_binder(ctx["enrollment"]["id"], h), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["lifecycle_status"] == "PENDING_EFFECTUATION"


def test_new_enrollment_has_both_initial_dimensions(api):
    """PRD §3.5: "The new enrollment is born with `lifecycle_status` of `PENDING_EFFECTUATION` and `payment_status` of `AWAITING_BINDER`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_payment_and_lifecycle_dimensions
    """
    ctx = setup_enrollment("app-6b", income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                           benchmark_gross=50_000)
    enr = ctx["enrollment"]
    assert enr["lifecycle_status"] == "PENDING_EFFECTUATION"
    assert enr["payment_status"] == "AWAITING_BINDER"


def test_member_edit_cascades_to_magi_fpl_and_household_version(api):
    """PRD §2.5: "Because adding or editing a member changes the household's income picture, the member operation cascades into the household, and the household version advances as a result; this cascade is the linchpin of the concurrency rules in §2."
    PRD §3.1: "The `fpl_percent` is then the household MAGI divided by that FPL annual figure, multiplied by 100, rounded half up to two decimal places."

    Design: Difficulty/transitive_cascade/member_edit_cascades_magi_then_fpl_then_version
    """
    hh, mem = create_household_with_primary("app-7", income_cents=3_000_000)
    h = make_applicant_headers("app-7")
    before = validate_success(api.get_household(hh["id"], h), 200)["version"]
    validate_success(api.update_member(hh["id"], mem["id"],
                                       {"annual_income_cents": 4_000_000}, h), 200)
    after = validate_success(api.get_household(hh["id"], h), 200)
    assert after["household_magi_cents"] == 4000000
    assert after["fpl_percent"] == 266.67
    assert after["version"] == before + 1


def test_member_add_recompute_keeps_fpl_consistent_with_magi(api):
    """PRD §3.1: "The household's countable income is the sum of `annual_income_cents` over the **countable members**."
    PRD §3.1: "the base poverty level of $15,000 (1,500,000 cents) for a household of one, plus an additional $5,300 (530,000 cents) for each person beyond the first — that is, the base plus 530,000 cents multiplied by one less than `countable_size`."

    Design: Difficulty/transitive_cascade/member_edit_cascades_magi_then_fpl_then_version
    """
    # size 1, magi 3000000, fpl annual 1500000 -> fpl 200.00.
    hh, _ = create_household_with_primary("app-7b", income_cents=3_000_000)
    h = make_applicant_headers("app-7b")
    got = validate_success(api.get_household(hh["id"], h), 200)
    assert got["household_magi_cents"] == 3000000
    assert got["fpl_percent"] == 200.00


def test_reopen_deletes_determination_and_clears_submitted_at(api):
    """PRD §3.3: "Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`."

    Design: Difficulty/transitive_cascade/reopen_deletes_determination_and_clears_submitted_at
    """
    ctx = setup_determined_application("app-8", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-8")
    reopened = validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    assert reopened["status"] == "DRAFT"
    assert reopened["submitted_at"] is None
    dets = validate_success(api.get_determination(ctx["application"]["id"], h), 200)
    assert isinstance(dets, list) and len(dets) == 0


def test_submitted_at_is_set_before_reopen_then_cleared(api):
    """PRD §3.2: "On a successful submit the server sets `submitted_at` to the current UTC clock, sets the application's `sep_request_id` to the `id` of the approved `SepRequest` when the window is `SEP`, increments the household's `version` by 1, and increments the application's `version` by 1."
    PRD §3.3: "Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`."

    Design: Difficulty/transitive_cascade/reopen_deletes_determination_and_clears_submitted_at
    """
    ctx = setup_determined_application("app-8b", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-8b")
    determined = validate_success(api.get_application(ctx["application"]["id"], h), 200)
    assert determined["submitted_at"] is not None
    reopened = validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    assert reopened["submitted_at"] is None
