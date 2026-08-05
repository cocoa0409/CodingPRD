"""Re-routing a declined referral: the chain cycle back into SENT, the shared
acknowledgement budget and the chain-wide re-route limit."""

from test_helpers import (
    ApiErrorId,
    assert_offering_counters,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_rerouting_a_declined_referral_returns_the_chain_to_sent(api):
    """PRD §3.4: "Instead a **new** referral is created in `SENT` with
    `parent_referral_id` naming the declined row, `root_referral_id` inherited
    from the declined row's own `root_referral_id`, and `reroute_count` one
    higher than the chain's current value."
    PRD §3.4: "That incremented `reroute_count` is then written onto **every**
    referral row sharing the same `root_referral_id`, incrementing each of those
    rows' `version` by 1, so the chain's re-route budget is readable from any
    member."
    PRD §3.4: "The declined row itself is not re-stated — it stays `DECLINED`
    for audit."

    Design: Difficulty/non_linear_state_machine/referral_decline_reroute_cycle_returns_chain_to_sent
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-005", mrn="MRN-050", full_name="Nia Bell", household_size=3,
    )
    org_a, offering_a, partner_a = fx.org_with_offering(capacity_total=5)
    org_b, offering_b, _partner_b = fx.org_with_offering(
        capacity_total=5,
        org_overrides={
            "name": "Southside Pantry", "contact_email": "ops@southside.example"
        },
    )

    root = fx.send_referral(
        chw_headers, patient["id"], offering_a["id"], worker["id"]
    )
    fx.respond_to_referral(
        partner_a, root["id"], "DECLINED", "No boxes matching dietary needs"
    )

    child = validate_success(
        api.reroute_referral(
            root["id"],
            {
                "offering_id": offering_b["id"],
                "urgency": "ROUTINE",
                "units_requested": 1,
                "expected_offering_version": fx.offering_version(offering_b["id"]),
            },
            chw_headers,
        ),
        201,
    )

    assert child["status"] == "SENT", (
        f"the re-route puts the chain back into SENT, got {child['status']}"
    )
    assert child["parent_referral_id"] == root["id"]
    assert child["root_referral_id"] == root["id"], (
        "the child inherits the declined row's own root_referral_id"
    )
    assert child["reroute_count"] == 1

    predecessor = fx.read_referral(root["id"])
    assert predecessor["reroute_count"] == 1, (
        "the incremented count is written back onto every row in the chain"
    )
    assert predecessor["status"] == "DECLINED", (
        "the declined predecessor is retained for audit and is not re-stated"
    )


def test_the_reroute_moves_the_hold_onto_the_alternate_offering(api):
    """PRD §3.4: "The new row places a hold on the alternate offering exactly as
    a root referral does, including the exhaustion cascade and its escalation,
    and computes its `ack_deadline_at` under the root-chain-budget variant."
    PRD §3.4: "Referrals can be read individually and listed, with the listing
    filtering on `patient_id`, `offering_id`, `opened_by_chw_id`,
    `parent_referral_id`, `root_referral_id` and `status` — the last two
    together let an operator pull an entire re-route chain or find every child
    of a given parent."

    Design: Difficulty/non_linear_state_machine/referral_decline_reroute_cycle_returns_chain_to_sent
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-005B", mrn="MRN-050B", full_name="Nia Bell", household_size=3,
    )
    org_a, offering_a, partner_a = fx.org_with_offering(capacity_total=5)
    org_b, offering_b, _partner_b = fx.org_with_offering(
        capacity_total=5,
        org_overrides={
            "name": "Southside Pantry", "contact_email": "ops@southside.example"
        },
    )

    root = fx.send_referral(chw_headers, patient["id"], offering_a["id"], worker["id"])
    fx.respond_to_referral(
        partner_a, root["id"], "DECLINED", "No boxes matching dietary needs"
    )
    fx.reroute_referral(chw_headers, root["id"], offering_b["id"])

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"root_referral_id": root["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the chain now holds two rows, got {meta['total_count']}"
    )

    assert_offering_counters(
        fx.read_offering(offering_b["id"]),
        available=4, allocated=1, lifetime=1,
    )
    assert_offering_counters(
        fx.read_offering(offering_a["id"]),
        available=5, allocated=0, released=1, lifetime=1,
    )


def test_a_rerouted_child_inherits_the_root_chain_acknowledgement_budget(api):
    """PRD §3.4: "Under the **root-chain-budget** variant, which applies
    whenever `parent_referral_id` is not null, the whole re-route chain shares
    one acknowledgement budget: `ack_deadline_at` is the *root* referral's
    `sent_at` plus the urgency's hours."
    PRD §3.4: "`hold_expires_at`, by contrast, has no such subtlety in either
    variant — it is always this row's own `sent_at` plus 168 hours, that is,
    seven days."

    Design: Corner/state_machines/reroute_child_inherits_root_chain_ack_budget
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-019",
        mrn="MRN-C19", full_name="Chain Case",
    )
    org_a, offering_a, partner_a = fx.org_with_offering(capacity_total=4)
    org_b, offering_b, _partner_b = fx.org_with_offering(
        capacity_total=4,
        org_overrides={
            "name": "Southside Pantry", "contact_email": "ops@southside.example"
        },
    )

    root = fx.send_referral(
        chw_headers, patient["id"], offering_a["id"], worker["id"], urgency="URGENT"
    )
    fx.respond_to_referral(partner_a, root["id"], "DECLINED", "Out of stock")

    fx.set_clock("2026-06-02T12:00:00Z")
    child = fx.reroute_referral(
        chw_headers, root["id"], offering_b["id"], urgency="URGENT"
    )

    assert_same_instant(
        fx.read_referral(root["id"])["ack_deadline_at"], "2026-06-02T00:00:00Z",
        "root ack_deadline_at",
    )
    assert_same_instant(child["sent_at"], "2026-06-02T12:00:00Z", "child sent_at")
    assert_same_instant(
        child["ack_deadline_at"], "2026-06-02T00:00:00Z",
        "child ack_deadline_at anchored at the root's sent_at",
    )
    assert_same_instant(
        child["hold_expires_at"], "2026-06-09T12:00:00Z",
        "child hold_expires_at (its own sent_at plus 168 hours)",
    )
    assert child["status"] == "SENT"
    assert child["reroute_count"] == 1


def test_a_third_reroute_on_the_same_chain_is_refused(api):
    """PRD §3.4: "Two preconditions are specific to re-routing and sit between
    those: the referral being re-routed must be in `DECLINED`, checked at rung
    8, and the chain's `reroute_count` must be strictly less than 2, checked at
    rung 14 — a chain already re-routed twice cannot be re-routed a third time
    and is rejected with `ERR_REROUTE_LIMIT_EXCEEDED`."

    Design: Corner/validations/third_reroute_exceeds_chain_limit
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-036", mrn="MRN-C36", full_name="Reroute Case",
    )
    org, offering_a, partner_headers = fx.org_with_offering(capacity_total=5)
    offering_b = fx.create_offering(org["id"], capacity_total=5)
    offering_c = fx.create_offering(org["id"], capacity_total=5)
    offering_d = fx.create_offering(org["id"], capacity_total=5)

    chain = fx.referral_chain_at_limit(
        chw_headers, partner_headers, patient["id"], worker["id"],
        [offering_a, offering_b, offering_c],
    )

    response = api.reroute_referral(
        chain[2]["id"],
        {
            "offering_id": offering_d["id"],
            "urgency": "ROUTINE",
            "units_requested": 1,
            "expected_offering_version": fx.offering_version(offering_d["id"]),
        },
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_REROUTE_LIMIT_EXCEEDED.value, 422)

    for row in chain:
        reread = fx.read_referral(row["id"])
        assert reread["reroute_count"] == 2, (
            f"the chain-wide count sits at 2, got {reread['reroute_count']} on {row['id']}"
        )
    assert fx.read_referral(chain[2]["id"])["root_referral_id"] == chain[0]["id"]

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"root_referral_id": chain[0]["id"]})
    )
    assert meta["total_count"] == 3, (
        f"the refused fourth referral was never created, got {meta['total_count']}"
    )
    assert_offering_counters(
        fx.read_offering(offering_d["id"]), available=5, lifetime=0
    )
