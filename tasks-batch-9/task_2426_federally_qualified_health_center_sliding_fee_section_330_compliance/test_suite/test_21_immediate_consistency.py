"""Every dependent value settles inside the request that caused it to move."""

from test_helpers import (
    OFFICER,
    REP,
    api_client,
    decide_waiver_payload,
    refresh_encounter,
    refresh_patient,
    setup_boot_pt,
    setup_encounter,
    setup_requested_waiver,
    validate_success,
)


def test_a_granted_waiver_settles_the_ledger_in_the_same_response():
    """The decide response already carries the waived amount, and the reads agree at once.

    PRD 2.8: "They are stored for reading convenience, but their stored value must equal a
    fresh recount at the end of every request, with a drift tolerance of exactly zero. Any
    request that changes a contributing row must recompute them in the same request, and a
    request that *undoes* an earlier change must restore them to the value they held
    before it."

    PRD 3.6: "`REQUESTED → GRANTED` fires a three-hop cascade. The waiver's own
    `waived_amount_cents` is set to the encounter's `patient_charge_cents` and the same
    amount is copied onto the encounter's `waived_amount_cents`. In the first hop, because
    the encounter's `waived_amount_cents` changed, the patient's `patient_balance_cents` is
    reduced by that amount and the patient's `version` increments by one."

    PRD 3.6: "Requesting a waiver mutates nothing on the encounter and nothing on the
    patient's ledger."

    Design: Corner/consistency_model/granted_waiver_is_visible_immediately_in_the_same_response
    """
    ctx = setup_boot_pt()
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=8000,
    )
    assert encounter["patient_charge_cents"] == 2500
    waiver = setup_requested_waiver(encounter, waiver_reason="NO_INCOME", headers=REP)
    assert waiver["status"] == "REQUESTED"
    assert waiver["waived_amount_cents"] == 0
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500, (
        "the request alone moved nothing on the ledger"
    )

    granted = validate_success(
        api_client.decide_waiver(
            waiver["id"],
            decide_waiver_payload(
                "GRANT", decision_note="Household reports no income this year"
            ),
            OFFICER,
        )
    )

    assert granted["status"] == "GRANTED"
    assert granted["waived_amount_cents"] == 2500, (
        "the decide response itself carries the settled amount, got "
        f"{granted['waived_amount_cents']}"
    )
    assert granted["decided_by_user_id"] == "co-1"

    settled_encounter = refresh_encounter(encounter["id"])
    assert settled_encounter["waived_amount_cents"] == 2500, (
        "the very next read of the encounter already agrees"
    )
    assert settled_encounter["patient_charge_cents"] == 2500, (
        "the charge is unchanged; only the waiver offsets it"
    )
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0, (
        "the ledger reached zero without any convergence step"
    )
