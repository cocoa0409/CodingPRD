"""compute_overall_result: any-FAIL aggregation that may differ between the
initial-completion variant and the post-dispute-recompute variant when the
disputed result flips PASS.
"""
from test_helpers import (
    validate_success,
    order_complete_with_results, order_complete_consider_with_adverse_action,
    make_recruiter_headers, make_applicant_headers,
)
from test_helpers.fixtures import (
    dispute_verification, resolve_verification, api_client,
)


def test_two_orders_side_by_side_all_pass_clear_one_fail_consider(api):
    """An all-PASS order yields overall_result=CLEAR; a one-FAIL order
    yields CONSIDER. The branch is the non-linear "if any FAIL" rule.

    PRD §3.4: "The calculation reads the three effective results and
    returns `CONSIDER` if any one of them is `FAIL`, otherwise `CLEAR`."

    Design: Difficulty/combinatorial_formula/overall_result_three_input_nonlinear_branching
    """
    # Order A: all PASS.
    (_, _, _, _, orderA, _, _, _) = order_complete_with_results(
        crim_result="PASS", mvr_result="PASS", edu_result="PASS",
        state_code="WA", recruiter_id="rec-bob",
    )
    # Order B: EDUCATION FAIL — use a different state_code because each
    # create_jurisdiction call requires a unique state_code (PRD §3.1).
    (_, _, _, _, orderB, _, _, _) = order_complete_with_results(
        crim_result="PASS", mvr_result="PASS", edu_result="FAIL",
        state_code="OR", recruiter_id="rec-bob",
    )
    a = validate_success(api.get_order(orderA["id"],
                                        make_recruiter_headers("rec-bob")), 200)
    b = validate_success(api.get_order(orderB["id"],
                                        make_recruiter_headers("rec-bob")), 200)
    assert a["status"] == "COMPLETE", f"order A must be COMPLETE, got {a['status']!r}"
    assert a["overall_result"] == "CLEAR", \
        f"all-PASS order must be CLEAR, got {a['overall_result']!r}"
    assert b["status"] == "COMPLETE", f"order B must be COMPLETE, got {b['status']!r}"
    assert b["overall_result"] == "CONSIDER", \
        f"any-FAIL order must be CONSIDER, got {b['overall_result']!r}"


def test_post_dispute_recompute_flips_overall_result_from_consider_to_clear(api):
    """Initially CRIMINAL=FAIL → overall_result=CONSIDER. After dispute and
    resolve with new_result=PASS, the post-dispute recompute variant reads
    the new value and overall_result flips to CLEAR.

    PRD §3.4: "The order's `overall_result` is computed at the moment the
    order's `status` reaches `COMPLETE`, and recomputed whenever a child
    verification changes status while the order is `COMPLETE`. Each
    verification contributes its current effective `result`: a `REPORTED`
    row contributes its `result`; a `DISPUTED` row continues to contribute
    its original `result` while the dispute is open; a `RESOLVED` row
    contributes the post-resolution `result`, which may differ from what
    was originally reported"
    PRD §3.4: "The initial completion variant reads each child's reported
    `result`; the post-dispute recompute variant reads each child's
    current `result`, where the just-resolved row's value may have flipped
    from `FAIL` to `PASS`, so the two variants can produce different
    `overall_result` values for what started as identical inputs."
    PRD §3.5: "On success the verification advances from `DISPUTED` to
    `RESOLVED`, the `result` field is replaced with the `new_result`, and
    the `version` is incremented. If the parent order's `status` is
    `COMPLETE`, the order's `overall_result` is recomputed and the order's
    `version` is incremented."

    Design: Difficulty/dual_variant_calc/overall_result_post_dispute_recompute_flips_consider_to_clear
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(
            state_code="NY", recruiter_id="rec-alice",
            crim_payload={"conviction": "expunged"},
        )
    )
    initial = validate_success(api.get_order(order["id"],
                                              make_recruiter_headers("rec-alice")), 200)
    assert initial["overall_result"] == "CONSIDER", \
        f"initial overall_result with CRIMINAL=FAIL must be CONSIDER, got {initial['overall_result']!r}"
    # Dispute CRIMINAL, then resolve with new_result=PASS.
    crim_after_report = validate_success(
        api.get_verification(crim["id"], make_recruiter_headers("rec-alice")), 200,
    )
    disputed = dispute_verification(crim["id"], "expungement on record",
                                    crim_after_report["version"], applicant["id"])
    resolve_verification(crim["id"], "PASS", disputed["version"])
    final = validate_success(api.get_order(order["id"],
                                            make_recruiter_headers("rec-alice")), 200)
    assert final["overall_result"] == "CLEAR", \
        f"post-dispute recompute with new_result=PASS must yield CLEAR, got {final['overall_result']!r}"
