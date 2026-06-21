"""Compatibility scoring, scoring-mode variants, and the match-request lifecycle.

Translates queue-A (Difficulty) instances for dual_variant_calc (compatibility),
combinatorial_formula (compatibility), non_linear_state_machine (withdraw/reapply),
boundary_precision_check (accept threshold), plus queue-B matching corner instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    create_profile_payload,
    create_listing_payload,
    create_match_request_payload,
    create_profile,
    create_listing,
)

api = api_client


def _profile(full_name, **over):
    return create_profile(api, full_name=full_name, **over)


def test_compatibility_three_factor_nonlinear_score():
    """PRD §3.1: "The base score is the cleanliness fit multiplied by 40, plus the
    sleep fit multiplied by 30, plus the lifestyle fit multiplied by 30, giving a
    value on a 0-to-100 range, which is then rounded half-up to a whole integer."

    Applicant cleanliness 3 vs wants 5 -> clean_fit 0.6 -> 24; sleep match -> 30;
    lifestyle full -> 30; total 84.

    Design: Difficulty/combinatorial_formula/compatibility_nonlinear_three_factor
    """
    lister = _profile("L3", cleanliness=5, sleep_schedule="EARLY_BIRD")
    applicant = _profile("C3", cleanliness=3, sleep_schedule="EARLY_BIRD")
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=False, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"], scoring_mode="STRICT"),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 84


def test_compatibility_three_factor_second_combination():
    """PRD §3.1: "The base score is the cleanliness fit multiplied by 40, plus the
    sleep fit multiplied by 30, plus the lifestyle fit multiplied by 30, giving a
    value on a 0-to-100 range, which is then rounded half-up to a whole integer."

    Applicant cleanliness 2 vs wants 5 -> clean_fit max(0,5-3)/5 = 0.4 -> 16; sleep
    match -> 30; lifestyle full -> 30; total 76.

    Design: Difficulty/combinatorial_formula/compatibility_nonlinear_three_factor
    """
    lister = _profile("L3b", cleanliness=5, sleep_schedule="EARLY_BIRD")
    applicant = _profile("C3b", cleanliness=2, sleep_schedule="EARLY_BIRD")
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=False, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"], scoring_mode="STRICT"),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 76


def test_strict_dealbreaker_hard_zeroes_score():
    """PRD §3.2: "Under `STRICT`, if either dealbreaker is actually violated — that is,
    the listing forbids smokers and the applicant smokes, or the listing forbids pets
    and the applicant keeps pets — the score is forced to exactly 0 regardless of the
    other factors."

    Design: Difficulty/dual_variant_calc/compatibility_strict_vs_lenient_diverge
    """
    lister = _profile("L2", cleanliness=5, sleep_schedule="EARLY_BIRD")
    smoker = _profile("S2", cleanliness=5, sleep_schedule="EARLY_BIRD", smoker=True)
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=True, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], smoker["id"], scoring_mode="STRICT"),
            make_roommate_headers(smoker["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 0


def test_lenient_dealbreaker_only_subtracts_half_of_lifestyle():
    """PRD §3.2: "Under `LENIENT`, no hard-zeroing occurs: the dealbreakers only subtract
    their 0.5 each from the lifestyle fit, and the rounded weighted value stands as the
    score."

    Smoker vs no_smokers, otherwise perfect: 40 (clean) + 30 (sleep) + 15 (lifestyle
    0.5*30) = 85.

    Design: Difficulty/dual_variant_calc/compatibility_strict_vs_lenient_diverge
    """
    lister = _profile("L2b", cleanliness=5, sleep_schedule="EARLY_BIRD")
    smoker = _profile("S2b", cleanliness=5, sleep_schedule="EARLY_BIRD", smoker=True)
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=True, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], smoker["id"], scoring_mode="LENIENT"),
            make_roommate_headers(smoker["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 85


def test_match_request_starts_pending():
    """PRD §3.2: "A `MatchRequest` opens in `PENDING` and can travel to `ACCEPTED`,
    `REJECTED`, or `WITHDRAWN`; of these, `ACCEPTED` and `REJECTED` are terminal, while
    `WITHDRAWN` is a way-station that can cycle back."

    Design: Corner/state_machines/match_request_initial_state_pending
    """
    lister = _profile("IniL")
    applicant = _profile("IniM")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"]),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["status"] == "PENDING"


def test_withdraw_then_reapply_returns_to_pending_and_recomputes_score():
    """PRD §3.2: "A withdrawn request can be revived by the same applicant through a
    re-apply, provided the listing is still `OPEN`; re-applying carries the request from
    `WITHDRAWN` back to `PENDING` and recomputes the `compatibility_score` against the
    listing's current preferences."

    Perfect fit (clean 5 vs wants 5 -> max(0,5-0)/5=1.0 -> 40, sleep FLEXIBLE -> 30,
    lifestyle -> 30) = 100.

    Design: Difficulty/non_linear_state_machine/match_request_withdraw_reapply_cycle
    """
    lister = _profile("L5")
    applicant = _profile("M5", cleanliness=5, sleep_schedule="FLEXIBLE")
    listing = create_listing(api, lister, wants_cleanliness=5, wants_sleep_schedule="FLEXIBLE")
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"]),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    applicant_headers = make_roommate_headers(applicant["id"])
    validate_success(api.withdraw_match_request(mr["id"], applicant_headers))
    reapplied = validate_success(api.reapply_match_request(mr["id"], applicant_headers))
    assert reapplied["status"] == "PENDING"
    assert reapplied["compatibility_score"] == 100


def test_withdraw_moves_to_withdrawn_then_reapply_re_enters_pending():
    """PRD §3.2: "Withdrawal belongs to the applicant: the acting roommate must be the
    request's `applicant_id`, and withdrawal moves a `PENDING` request to `WITHDRAWN`."
    PRD §3.2: "re-applying carries the request from `WITHDRAWN` back to `PENDING` and
    recomputes the `compatibility_score` against the listing's current preferences."

    Design: Difficulty/non_linear_state_machine/match_request_withdraw_reapply_cycle
    """
    lister = _profile("L5b")
    applicant = _profile("M5b", cleanliness=5, sleep_schedule="FLEXIBLE")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"]),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    applicant_headers = make_roommate_headers(applicant["id"])
    withdrawn = validate_success(api.withdraw_match_request(mr["id"], applicant_headers))
    assert withdrawn["status"] == "WITHDRAWN"
    reapplied = validate_success(api.reapply_match_request(mr["id"], applicant_headers))
    assert reapplied["status"] == "PENDING"


def test_accept_at_or_above_threshold_succeeds():
    """PRD §3.2: "The applicant's frozen `compatibility_score` must also reach the
    platform's match threshold of 60; a request whose score is below 60 cannot be
    accepted and is rejected with `ERR_BELOW_MATCH_THRESHOLD`."

    Applicant scores 70 (clean 5 vs 5 -> 40, sleep mismatch -> 0, lifestyle -> 30),
    which reaches 60 and is accepted.

    Design: Difficulty/boundary_precision_check/match_score_above_threshold_accepts
    """
    lister = _profile("L11", cleanliness=5, sleep_schedule="EARLY_BIRD")
    applicant = _profile("T11", cleanliness=5, sleep_schedule="NIGHT_OWL")
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=False, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"], scoring_mode="STRICT"),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 70
    accepted = validate_success(api.accept_match_request(mr["id"], make_roommate_headers(lister["id"])))
    assert accepted["status"] == "ACCEPTED"


def test_accept_perfect_score_well_above_threshold_succeeds():
    """PRD §3.2: "The applicant's frozen `compatibility_score` must also reach the
    platform's match threshold of 60; a request whose score is below 60 cannot be
    accepted and is rejected with `ERR_BELOW_MATCH_THRESHOLD`."

    A perfect-fit applicant scores 100 (clean 5 vs wants 5 -> max(0,5-0)/5=1.0 -> 40,
    sleep FLEXIBLE -> 30, lifestyle -> 30), comfortably above 60, and is accepted.

    Design: Difficulty/boundary_precision_check/match_score_above_threshold_accepts
    """
    lister = _profile("L11b")
    applicant = _profile("T11b", cleanliness=5, sleep_schedule="FLEXIBLE")
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="FLEXIBLE",
        no_smokers=False, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"], scoring_mode="STRICT"),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 100
    accepted = validate_success(api.accept_match_request(mr["id"], make_roommate_headers(lister["id"])))
    assert accepted["status"] == "ACCEPTED"


def test_accept_below_threshold_rejected():
    """PRD §3.2: "a request whose score is below 60 cannot be accepted and is rejected
    with `ERR_BELOW_MATCH_THRESHOLD`."

    Applicant scores 38 (clean 1 vs 5 -> 8, sleep mismatch -> 0, lifestyle -> 30).

    Design: Corner/validations/below_threshold_accept_rejected
    """
    lister = _profile("BlwL", cleanliness=5, sleep_schedule="EARLY_BIRD")
    applicant = _profile("BlwP", cleanliness=1, sleep_schedule="NIGHT_OWL")
    listing = create_listing(
        api, lister, wants_cleanliness=5, wants_sleep_schedule="EARLY_BIRD",
        no_smokers=False, no_pets=False,
    )
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"], scoring_mode="STRICT"),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    assert mr["compatibility_score"] == 38
    resp = api.accept_match_request(mr["id"], make_roommate_headers(lister["id"]))
    validate_error(resp, ApiErrorId.ERR_BELOW_MATCH_THRESHOLD.value)


def test_self_application_rejected():
    """PRD §3.1: "The applicant may not be the lister of the same listing; a
    self-application is rejected with `ERR_SELF_APPLICATION`."

    Design: Corner/validations/self_application_rejected
    """
    lister = _profile("SelfL")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    resp = api.create_match_request(
        create_match_request_payload(listing["id"], lister["id"]),
        make_roommate_headers(lister["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPLICATION.value)


def test_accept_already_accepted_is_invalid_state():
    """PRD §3.2: "an action requested from a state where it is not defined is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_already_accepted_match_request_invalid_state
    """
    lister = _profile("AccL")
    applicant = _profile("AccM", cleanliness=5, sleep_schedule="FLEXIBLE")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"]),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    lister_headers = make_roommate_headers(lister["id"])
    validate_success(api.accept_match_request(mr["id"], lister_headers))
    resp = api.accept_match_request(mr["id"], lister_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_filtered_list_match_requests_by_listing():
    """PRD §2.3: "Unless otherwise specified, all list endpoints return resources sorted
    by their creation timestamp in ascending order."

    The listing's own match request appears when listing GET /match-requests filtered by
    that listing_id (a containment check robust to whether the optional filter narrows
    or not).

    Design: Corner/endpoints/filtered_list_match_requests_by_listing
    """
    lister = _profile("FltL")
    applicant = _profile("FltM", cleanliness=5, sleep_schedule="FLEXIBLE")
    listing = create_listing(api, lister, wants_cleanliness=1, wants_sleep_schedule="FLEXIBLE")
    mr = validate_success(
        api.create_match_request(
            create_match_request_payload(listing["id"], applicant["id"]),
            make_roommate_headers(applicant["id"]),
        ),
        201,
    )
    resp = api.list_match_requests(
        make_roommate_headers(lister["id"]), params={"listing_id": listing["id"]}
    )
    data = validate_success(resp)
    ids = [row["id"] for row in data]
    assert mr["id"] in ids
