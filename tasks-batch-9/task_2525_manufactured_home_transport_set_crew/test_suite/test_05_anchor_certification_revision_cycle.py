"""The anchoring package's revision cycle: SUBMITTED -> CHANGES_REQUIRED -> SUBMITTED.

Every test here walks the same certification row around the cycle described in
PRD §3.8 and watches `revision_round`, `hud_pass` and `state_pass` move on that
one id.
"""

from test_helpers import (
    ANCHOR_INSPECTOR_USER_ID,
    ApiErrorId,
    api_client,
    book_set_job,
    make_inspector_headers,
    make_set_crew_lead_headers,
    open_order,
    read_anchor_certification,
    register_plant,
    register_set_crew,
    resubmit_anchor_certification_payload,
    review_anchor_certification,
    review_anchor_certification_payload,
    set_logical_clock,
    submit_anchor_certification,
    validate_error,
    validate_success,
)


def _package_sent_back_for_changes(
    destination_state="AZ",
    wind_zone="I",
    section_count=1,
    anchor_count=6,
    strap_count=6,
):
    """A booked set job whose anchoring package sits in `CHANGES_REQUIRED`.

    The package is deliberately submitted short of the zone's required anchor
    count so that both verdicts are false and the inspector's `REQUEST_CHANGES`
    decision is the natural one.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(license_expiry_date="2027-06-30")
    order = open_order(
        plant["id"],
        section_count=section_count,
        destination_state=destination_state,
        wind_zone=wind_zone,
    )
    set_job = book_set_job(order["id"], set_crew["id"], labor_base_cents=480000)
    certification = submit_anchor_certification(
        set_job["id"],
        set_crew["id"],
        anchor_count=anchor_count,
        avg_torque_ft_lb=180,
        strap_count=strap_count,
        pier_count=6,
    )
    review_anchor_certification(
        certification["id"],
        decision="REQUEST_CHANGES",
        inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
    )
    return {
        "plant": plant,
        "set_crew": set_crew,
        "order": order,
        "set_job": set_job,
        "certification": read_anchor_certification(certification["id"]),
    }


def test_resubmission_returns_same_row_to_submitted_with_round_two():
    """PRD §3.8: "A decision of `REQUEST_CHANGES` moves it `SUBMITTED → CHANGES_REQUIRED`."
    PRD §3.8: "When changes have been requested, the job's `SetCrewLead` resubmits
    corrected figures on the **same** row, moving it `CHANGES_REQUIRED → SUBMITTED`;
    the resubmission overwrites `anchor_count`, `avg_torque_ft_lb`, `strap_count`
    and `pier_count` from the payload, increments `revision_round` by 1, and
    re-runs the HUD and state evaluation."

    Design: Difficulty/non_linear_state_machine/anchor_certification_changes_required_cycle
    """
    scenario = _package_sent_back_for_changes()
    certification = scenario["certification"]
    cert_id = certification["id"]

    assert certification["status"] == "CHANGES_REQUIRED", (
        "REQUEST_CHANGES must leave the package in CHANGES_REQUIRED, got "
        f"{certification['status']}"
    )
    assert certification["revision_round"] == 1, (
        f"a freshly submitted package opens at revision_round 1, got "
        f"{certification['revision_round']}"
    )
    assert certification["hud_pass"] is False, (
        "six anchors fall short of the eight a single-section zone I home needs, "
        "so hud_pass must be false"
    )
    assert certification["state_pass"] is False, (
        "six anchors fall short of the state figure too, so state_pass must be false"
    )

    response = api_client.resubmit_anchor_certification(
        cert_id,
        resubmit_anchor_certification_payload(
            anchor_count=8, avg_torque_ft_lb=175, strap_count=8, pier_count=6
        ),
        make_set_crew_lead_headers(scenario["set_crew"]["id"]),
    )
    resubmitted = validate_success(response)

    assert resubmitted["id"] == cert_id, (
        f"the cycle must stay on one row: expected id {cert_id}, got {resubmitted['id']}"
    )
    assert resubmitted["status"] == "SUBMITTED", (
        f"CHANGES_REQUIRED -> SUBMITTED expected, got {resubmitted['status']}"
    )
    assert resubmitted["revision_round"] == 2, (
        f"revision_round must increment to 2, got {resubmitted['revision_round']}"
    )
    assert resubmitted["anchor_count"] == 8, (
        f"the resubmission overwrites anchor_count with 8, got {resubmitted['anchor_count']}"
    )
    assert resubmitted["strap_count"] == 8, (
        f"the resubmission overwrites strap_count with 8, got {resubmitted['strap_count']}"
    )
    assert resubmitted["hud_pass"] is True, (
        "eight anchors, eight straps and 175 foot-pounds satisfy every HUD arm, so "
        "the re-run evaluation must flip hud_pass to true"
    )
    assert resubmitted["state_pass"] is True, (
        "an AZ destination adds no anchors, so eight anchors satisfy state_pass too"
    )


def test_certification_follows_resubmission_that_clears_both_verdicts():
    """PRD §3.8: "`hud_pass` is true only when all three of the following hold: the
    `anchor_count` is at least that required figure, the `avg_torque_ft_lb` is at
    least one hundred and seventy-five foot-pounds, and the `strap_count` is at
    least one strap per installed anchor."
    PRD §3.8: "`state_pass` is a separate and stricter count test on the anchors
    alone: the `anchor_count` must be at least the HUD-required figure, plus four
    additional anchors when the order's `destination_state` is `KS` or `CO`, and
    plus nothing in any other destination state."
    PRD §3.8: "A decision of `CERTIFY` moves the package `SUBMITTED → CERTIFIED`,
    but only when both `hud_pass` and `state_pass` are true; if either is false the
    request is refused with `ERR_ANCHOR_COMPLIANCE_FAILED`."
    PRD §3.8: "Three decisions exist and each writes the acting `X-User-ID` into
    `certifier_user_id`."

    Design: Difficulty/non_linear_state_machine/anchor_certification_changes_required_cycle
    """
    scenario = _package_sent_back_for_changes()
    cert_id = scenario["certification"]["id"]

    resubmitted = validate_success(
        api_client.resubmit_anchor_certification(
            cert_id,
            resubmit_anchor_certification_payload(
                anchor_count=8, avg_torque_ft_lb=175, strap_count=8, pier_count=6
            ),
            make_set_crew_lead_headers(scenario["set_crew"]["id"]),
        )
    )
    assert resubmitted["hud_pass"] is True and resubmitted["state_pass"] is True, (
        "both verdicts must be true before the inspector can certify, got "
        f"hud_pass={resubmitted['hud_pass']}, state_pass={resubmitted['state_pass']}"
    )

    certified = validate_success(
        api_client.review_anchor_certification(
            cert_id,
            review_anchor_certification_payload(decision="CERTIFY"),
            make_inspector_headers(ANCHOR_INSPECTOR_USER_ID),
        )
    )

    assert certified["id"] == cert_id, (
        f"certification must land on the same row {cert_id}, got {certified['id']}"
    )
    assert certified["status"] == "CERTIFIED", (
        f"SUBMITTED -> CERTIFIED expected on the second round, got {certified['status']}"
    )
    assert certified["revision_round"] == 2, (
        f"the certified row still reports revision_round 2, got {certified['revision_round']}"
    )
    assert certified["certifier_user_id"] == ANCHOR_INSPECTOR_USER_ID, (
        "the reviewing inspector's identifier must be stored in certifier_user_id, "
        f"expected {ANCHOR_INSPECTOR_USER_ID}, got {certified['certifier_user_id']}"
    )


def test_resubmitted_package_short_of_the_state_figure_is_not_certified():
    """PRD §3.8: "`state_pass` is a separate and stricter count test on the anchors
    alone: the `anchor_count` must be at least the HUD-required figure, plus four
    additional anchors when the order's `destination_state` is `KS` or `CO`, and
    plus nothing in any other destination state."
    PRD §3.8: "A decision of `CERTIFY` moves the package `SUBMITTED → CERTIFIED`,
    but only when both `hud_pass` and `state_pass` are true; if either is false the
    request is refused with `ERR_ANCHOR_COMPLIANCE_FAILED`."

    Design: Difficulty/non_linear_state_machine/anchor_certification_changes_required_cycle
    """
    scenario = _package_sent_back_for_changes(destination_state="KS")
    cert_id = scenario["certification"]["id"]

    resubmitted = validate_success(
        api_client.resubmit_anchor_certification(
            cert_id,
            resubmit_anchor_certification_payload(
                anchor_count=8, avg_torque_ft_lb=180, strap_count=8, pier_count=6
            ),
            make_set_crew_lead_headers(scenario["set_crew"]["id"]),
        )
    )
    assert resubmitted["status"] == "SUBMITTED", (
        f"the resubmission returns the row to SUBMITTED, got {resubmitted['status']}"
    )
    assert resubmitted["revision_round"] == 2, (
        f"revision_round must increment to 2, got {resubmitted['revision_round']}"
    )
    assert resubmitted["hud_pass"] is True, (
        "eight anchors clear the HUD figure of eight for a single-section zone I home"
    )
    assert resubmitted["state_pass"] is False, (
        "a KS destination demands four anchors beyond the HUD figure, so eight "
        "anchors must leave state_pass false"
    )

    refused = api_client.review_anchor_certification(
        cert_id,
        review_anchor_certification_payload(decision="CERTIFY"),
        make_inspector_headers(ANCHOR_INSPECTOR_USER_ID),
    )
    validate_error(refused, ApiErrorId.ERR_ANCHOR_COMPLIANCE_FAILED.value)

    unchanged = read_anchor_certification(cert_id)
    assert unchanged["status"] == "SUBMITTED", (
        "a refused certification leaves the package in SUBMITTED, got "
        f"{unchanged['status']}"
    )
    assert unchanged["revision_round"] == 2, (
        f"a refused certification does not advance revision_round, got "
        f"{unchanged['revision_round']}"
    )
