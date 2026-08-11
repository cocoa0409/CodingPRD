"""Epoch-sweep credential expiry cascade: license expiry lapses its approved
dependency chain transitively, recomputes the case dimensions, and freezes the
open panel."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    TEST_USERS,
    create_physician, create_case, create_offer, extend_offer, accept_offer,
    execute_offer, get_case, get_credential_item,
    create_credential_item, approve_credential_item,
    complete_training, setup_ready_schedule, set_clock, run_epoch,
    get_panel_for_case,
)

PM = TEST_USERS["practice_manager_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]


def _setup_live_with_credential_chain():
    """Full go-live with a license <- DEA <- Medicare payer dependency chain,
    all APPROVED; the license alone expires 2027-08-01. Panel OPEN."""
    physician = create_physician(full_name="Dr. Hal")
    case = create_case(physician["id"])
    offer = create_offer(case)
    offer = extend_offer(offer["id"])
    offer = accept_offer(offer["id"], physician["id"])

    lic = create_credential_item(case["id"], "STATE_LICENSE", expires_on="2027-08-01")
    approve_credential_item(lic["id"])
    dea = create_credential_item(
        case["id"], "DEA_REGISTRATION", expires_on="2028-06-01",
        depends_on_item_ids=[lic["id"]],
    )
    approve_credential_item(dea["id"])
    mcr = create_credential_item(
        case["id"], "PAYER_ENROLLMENT_MEDICARE", depends_on_item_ids=[dea["id"]]
    )
    approve_credential_item(mcr["id"])

    offer = execute_offer(offer["id"])
    complete_training(case["id"], physician["id"])
    setup_ready_schedule(case["id"])
    set_clock("2027-06-01T09:00:00Z")
    panel = get_panel_for_case(case["id"])
    validate_success(api_client.open_panel(panel["id"], PM), 200)

    set_clock("2027-08-02T00:00:00Z")
    return {
        "physician": physician, "case": case, "panel": panel,
        "lic": lic, "dea": dea, "mcr": mcr,
    }


def test_license_expiry_cascade_item_hops(api):
    """PRD §2.4: "First it expires credential items whose `expires_on` is earlier than the current logical date, running the full dependency cascade described in §3.3."
    PRD §3.3: "The epoch sweep flips any item in `PENDING`, `DOCS_SUBMITTED`, `VERIFIED`, `FILED`, or `APPROVED` whose `expires_on` is earlier than the current logical date to `EXPIRED`, and expiry runs the same dependency cascade: direct dependents still in flight record `blocked_from_status` and become `BLOCKED`, direct dependents in `APPROVED` become `LAPSED`, and a dependent flipped by either rule triggers the same rule on its own dependents until no more flips occur."

    Design: Difficulty/transitive_cascade/license_expiry_cascade_freezes_panel
    """
    ctx = _setup_live_with_credential_chain()
    sweep = run_epoch()
    assert ctx["lic"]["id"] in sweep["expired_credential_ids"]
    assert ctx["dea"]["id"] not in sweep["expired_credential_ids"], (
        "DEA expires 2028-06-01 and the Medicare payer has no expiry; only the license sweeps"
    )
    assert ctx["mcr"]["id"] not in sweep["expired_credential_ids"]

    assert get_credential_item(ctx["lic"]["id"])["status"] == "EXPIRED"
    assert get_credential_item(ctx["dea"]["id"])["status"] == "LAPSED", (
        "an APPROVED direct dependent of an EXPIRED item lapses"
    )
    assert get_credential_item(ctx["mcr"]["id"])["status"] == "LAPSED", (
        "the second hop is caused by DEA's own lapse, not by the sweep directly"
    )


def test_license_expiry_cascade_freezes_panel(api):
    """PRD §3.3: "Then the case's `credential_status` is recomputed — it becomes `BLOCKED` whenever any item is `BLOCKED`, `EXPIRED`, or `LAPSED` — and `posture` is recomputed from the components; if the case's panel is `OPEN` and the recomputed posture has fallen below `GO_LIVE_READY`, the panel freezes, moving `OPEN` → `FROZEN` as described in §3.6."
    PRD §2.6: "Once an offer executes, the case is `CREDENTIALING` while `credential_status` is anything other than `COMPLETE`"

    Design: Difficulty/transitive_cascade/license_expiry_cascade_freezes_panel
    """
    ctx = _setup_live_with_credential_chain()
    assert get_case(ctx["case"]["id"])["posture"] == "LIVE"

    run_epoch()

    case = get_case(ctx["case"]["id"])
    assert case["credential_status"] == "BLOCKED"
    assert case["posture"] == "CREDENTIALING", "posture fell below GO_LIVE_READY out of LIVE"
    panel = get_success_data(api_client.get_panel(ctx["panel"]["id"], DIRECTOR))
    assert panel["status"] == "FROZEN"
