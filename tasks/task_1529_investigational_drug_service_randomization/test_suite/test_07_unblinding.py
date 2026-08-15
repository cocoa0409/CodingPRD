"""Emergency unblinding: the three-person rule, parallel subject state axes,
and the blinding-integrity auto-suspension cascade (PRD §3.5, §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    setup_pharmacy, setup_randomized_subject, create_unblinding_payload,
    get_study, get_site, get_subject,
)
from test_helpers import TEST_USERS, make_unblinded_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


def test_unblinding_request_on_open_label_study_rejected():
    """PRD §3.8: "The subject must be `RANDOMIZED` — otherwise
    `ERR_SUBJECT_NOT_RANDOMIZED` — and still `BLINDED`, and the study must
    actually have a blind to break: requesting an unblinding on an `OPEN_LABEL`
    study is rejected with `ERR_STUDY_OPEN_LABEL`."

    Design: Corner/validations/unblinding_request_on_open_label_study_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-13", kit_numbers=("K-OL",),
                           pharmacist_license="L-VAL-13",
                           study_overrides={"blinding_model": "OPEN_LABEL"})
    result = setup_randomized_subject(world, subject_number="SUB-OL")
    resp = api_client.create_unblinding_request(
        create_unblinding_payload(result["subject"]["id"], reason="SAE"), INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_STUDY_OPEN_LABEL.value, expected_status=422)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / subject_parallel_enrollment_and_blinding_dimensions
# ---------------------------------------------------------------------------

def _world_with_approved_unblinding(protocol_number="P-PAR-1", threshold=10,
                                    pharmacist_license="L-PAR-1",
                                    unblinded_licenses=("L-PAR-2", "L-PAR-3"),
                                    kit_number="K-P", arm_code="TRT-A"):
    """Randomized subject + an APPROVED unblinding request (decided by the
    first unblinded staff member)."""
    world = setup_pharmacy(protocol_number=protocol_number, kit_numbers=(kit_number,),
                           pharmacist_license=pharmacist_license,
                           unblinded_licenses=unblinded_licenses,
                           study_overrides={"unblinding_suspension_threshold_pct": threshold})
    result = setup_randomized_subject(world, subject_number="SUB-P",
                                      slot_kit_numbers=[kit_number])
    ub = get_success_data(api_client.create_unblinding_request(
        create_unblinding_payload(result["subject"]["id"], reason="Emergency SAE"),
        INVESTIGATOR))
    decider = world["unblinded"][0]
    ub = get_success_data(api_client.decide_unblinding_request(
        ub["id"], {"decision": "APPROVED"}, make_unblinded_pharmacist_headers(decider["id"])))
    return {**world, **result, "unblinding_request": ub, "arm_code": arm_code}


def test_unblinding_execute_flips_only_the_blinding_axis():
    """PRD §3.5: "Every subject carries two parallel and independent status
    axes: the enrollment axis `enrollment_status`, beginning at `SCREENING`, and
    the blinding axis `blinded_status`, beginning at `BLINDED`." PRD §3.8:
    "Execution copies the treatment arm from the subject's `ASSIGNED`
    randomization slot into the request's `revealed_arm_code` — masked to `null`
    for blinded roles per §2.8 — moves the request to the terminal `EXECUTED`,
    and flips the subject's blinding axis from `BLINDED` to `UNBLINDED`."

    Design: Difficulty/non_linear_state_machine/subject_parallel_enrollment_and_blinding_dimensions
    """
    world = _world_with_approved_unblinding()
    executor = world["unblinded"][1]
    executed = get_success_data(api_client.execute_unblinding_request(
        world["unblinding_request"]["id"], make_unblinded_pharmacist_headers(executor["id"])))
    assert executed["status"] == "EXECUTED"
    assert executed["revealed_arm_code"] == world["arm_code"]
    subject = get_subject(world["subject"]["id"])
    assert subject["blinded_status"] == "UNBLINDED"
    assert subject["enrollment_status"] == "RANDOMIZED", (
        "the blinding axis moved while the enrollment axis stayed untouched"
    )


def test_unblinded_subject_can_still_withdraw_on_enrollment_axis():
    """PRD §3.5: "Moving a `RANDOMIZED` subject to `COMPLETED` or to `WITHDRAWN`
    is blocked while any of the subject's dispensing records remains `ACTIVE`,
    surfacing `ERR_ACTIVE_DISPENSING_EXISTS`; both destination states are
    terminal." PRD §3.8: "when one hundred times `unblinded_subject_count` is
    greater than or equal to `unblinding_suspension_threshold_pct` multiplied by
    `randomized_subject_count` — and at least one subject has been randomized,
    so the rule never fires on an empty denominator — the study suspends itself
    from `ACTIVE` to `SUSPENDED`, cascading every `ACTIVE` site to `ON_HOLD`
    (§3.1)."

    Design: Difficulty/non_linear_state_machine/subject_parallel_enrollment_and_blinding_dimensions
    """
    world = _world_with_approved_unblinding()
    executor = world["unblinded"][1]
    get_success_data(api_client.execute_unblinding_request(
        world["unblinding_request"]["id"], make_unblinded_pharmacist_headers(executor["id"])))
    # 1 unblinded of 1 randomized: 100 >= 10 -> the study auto-suspends.
    assert get_study(world["study"]["id"])["status"] == "SUSPENDED"
    assert get_site(world["site"]["id"])["status"] == "ON_HOLD"
    # The enrollment axis still moves independently: no ACTIVE dispensing, so
    # the withdrawal succeeds while the blinding axis stays UNBLINDED.
    withdrawn = get_success_data(api_client.transition_subject(
        world["subject"]["id"], {"to": "WITHDRAWN", "reason": "Physician decision"},
        world["pharmacist_headers"]))
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert withdrawn["blinded_status"] == "UNBLINDED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / unblinding_execute_cascades_to_study_suspension_and_site_hold
# ---------------------------------------------------------------------------

def test_unblinding_execute_reveals_arm_and_unblinds_subject():
    """PRD §3.8: "Execution copies the treatment arm from the subject's
    `ASSIGNED` randomization slot into the request's `revealed_arm_code` —
    masked to `null` for blinded roles per §2.8 — moves the request to the
    terminal `EXECUTED`, and flips the subject's blinding axis from `BLINDED` to
    `UNBLINDED`."

    Design: Difficulty/transitive_cascade/unblinding_execute_cascades_to_study_suspension_and_site_hold
    """
    world = _world_with_approved_unblinding(protocol_number="P-CAS-2",
                                            pharmacist_license="L-CAS2-1",
                                            unblinded_licenses=("L-CAS2-2", "L-CAS2-3"),
                                            kit_number="K-U")
    executor = world["unblinded"][1]
    executed = get_success_data(api_client.execute_unblinding_request(
        world["unblinding_request"]["id"], make_unblinded_pharmacist_headers(executor["id"])))
    assert executed["status"] == "EXECUTED"
    assert executed["revealed_arm_code"] == "TRT-A"
    assert get_subject(world["subject"]["id"])["blinded_status"] == "UNBLINDED"


def test_unblinding_execute_cascades_to_study_suspension_and_site_hold():
    """PRD §3.8: "the study suspends itself from `ACTIVE` to `SUSPENDED`,
    cascading every `ACTIVE` site to `ON_HOLD` (§3.1). Under the default
    threshold of 10, a study suspends once its unblinded subjects reach ten
    percent of its randomized population."

    Design: Difficulty/transitive_cascade/unblinding_execute_cascades_to_study_suspension_and_site_hold
    """
    world = _world_with_approved_unblinding(protocol_number="P-CAS-2B",
                                            pharmacist_license="L-CAS2-1",
                                            unblinded_licenses=("L-CAS2-2", "L-CAS2-3"),
                                            kit_number="K-U")
    executor = world["unblinded"][1]
    get_success_data(api_client.execute_unblinding_request(
        world["unblinding_request"]["id"], make_unblinded_pharmacist_headers(executor["id"])))
    # 1 unblinded of 1 randomized = 100% >= the 10% threshold.
    assert get_study(world["study"]["id"])["status"] == "SUSPENDED"
    assert get_site(world["site"]["id"])["status"] == "ON_HOLD"
