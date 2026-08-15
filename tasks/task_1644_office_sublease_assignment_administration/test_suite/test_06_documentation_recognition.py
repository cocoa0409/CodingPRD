"""Documentation, the recognition ceremony, and end-of-transfer compensation (PRD §3.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    B1,
    NON_EXISTENT_UUID,
    build_conditional_grant,
    build_documented_transfer,
    create_party,
    document_transfer,
    get_lease,
    get_recognition_of,
    get_transfer,
    make_landlord_headers,
    make_subtenant_headers,
    respond_condition,
    sign_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_document_creates_restoration_obligations(api):
    """PRD §3.7: "And for each accepted `RESTORATION_REQUIRED` condition, a restoration obligation is created in `OPEN`, carrying the negotiated `responsible_party` — `TENANT`, `SUBTENANT_OR_ASSIGNEE`, or `SHARED` — and `escrow_amount_cents` taken from the matching entry of `restoration_allocations`; fiscal coherence demands a strictly positive escrow whenever the responsible party is anything other than `TENANT`, else `ERR_FISCAL_INCOHERENT`, and an obligation recorded with a positive escrow auto-advances from `OPEN` to `ESCROW_POSTED`."

    Design: Corner/endpoints/document_creates_restoration_obligations_from_accepted_conditions
    """
    ctx = build_conditional_grant()  # RESTORATION_REQUIRED + ADDITIONAL_SECURITY
    for cond in ctx["conditions"]:
        respond_condition(cond["id"], ctx["pt"]["id"], "ACCEPTED")
    assert get_transfer(ctx["transfer"]["id"])["status"] == "CONSENT_GRANTED"

    receipt = validate_success(api.document_transfer_request(
        ctx["transfer"]["id"],
        {"executed_rent_per_rsf_annual_cents": 6400,
         "restoration_allocations": [{"responsible_party": "SUBTENANT_OR_ASSIGNEE",
                                      "escrow_amount_cents": 2500000}]},
        B1,
    ), 201)
    assert receipt["transfer_request_id"] == ctx["transfer"]["id"]

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "DOCUMENTED"

    obligations, _ = validate_paginated(
        api.list_transfer_restoration_obligations(ctx["transfer"]["id"], B1)
    )
    assert len(obligations) == 1, (
        "one obligation per accepted RESTORATION_REQUIRED condition"
    )
    obligation = obligations[0]
    assert obligation["responsible_party"] == "SUBTENANT_OR_ASSIGNEE"
    assert obligation["escrow_amount_cents"] == 2500000
    assert obligation["status"] == "ESCROW_POSTED", "positive escrow auto-advances OPEN"


def test_assignment_documentation_null_instrument(api):
    """PRD §3.7: "an `ASSIGNMENT` records no instrument, and the receipt's instrument reference is null."
    PRD §3.7: "A recognition agreement is always drafted, entering `DRAFTED` with its `sublease_agreement_id` set for a sublease and null for an assignment."
    PRD §3.7: "The transfer itself moves `CONSENT_GRANTED → DOCUMENTED`, and the broker receives a 201 documentation receipt naming the `transfer_request_id`, the `sublease_agreement_id` (null for assignments), and the `recognition_agreement_id` (always set)."

    Design: Corner/entities/assignment_documentation_null_instrument_and_assignee_signature
    """
    ctx = build_documented_transfer(counterparty_kind="ASSIGNEE", attest=False,
                                    transfer_overrides={"transfer_type": "ASSIGNMENT"},
                                    decide_overrides={"release_of_assignor": True})
    receipt = ctx["receipt"]
    assert receipt["sublease_agreement_id"] is None
    assert receipt["recognition_agreement_id"] is not None

    recognition = get_recognition_of(ctx["transfer"]["id"])
    assert recognition["sublease_agreement_id"] is None
    assert recognition["status"] == "DRAFTED"

    sign_recognition(recognition["id"], "LANDLORD", ctx["pl"]["id"], "ASSIGNEE")
    final = sign_recognition(recognition["id"], "COUNTERPARTY", ctx["ps"]["id"],
                             "ASSIGNEE")
    assert final["status"] == "FULLY_EXECUTED"

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "EFFECTIVE"
    assert transfer["liability_released"] is True, "release was elected at grant"

    instruments, _ = validate_paginated(
        api.list_sublease_agreements(B1, params={"transfer_request_id": ctx["transfer"]["id"]})
    )
    assert instruments == [], "an assignment records no instrument"


def test_sublease_agreement_filtered_list_by_transfer(api):
    """PRD §3.7: "instruments likewise list with `transfer_request_id`, `status`, and `demised_area_id` filters."
    PRD §3.7: "For a `SUBLEASE`, an instrument is minted in `EXECUTED` status, stamped with `executed_at` and pinned to the certified measurement through its `demised_area_id` — version-pinning on approval, so the closing paper always names the exact measurement it relies on"

    Design: Corner/endpoints/sublease_agreement_filtered_list_by_transfer
    """
    ctx = build_documented_transfer()
    data, _ = validate_paginated(
        api.list_sublease_agreements(B1, params={"transfer_request_id": ctx["transfer"]["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == ctx["sa_id"]
    assert data[0]["status"] == "EXECUTED"

    empty, meta = validate_paginated(
        api.list_sublease_agreements(B1, params={"transfer_request_id": NON_EXISTENT_UUID})
    )
    assert empty == [], "an unknown filter value yields an empty page, not a 404"
    assert meta["total_count"] == 0


def test_signatory_identity_mismatch(api):
    """PRD §2.9: "Signing with `signatory` set to `LANDLORD` requires the caller's `X-User-ID` to equal the lease's `landlord_party_id`; signing with `signatory` set to `COUNTERPARTY` requires it to equal the transfer's `counterparty_id`; and neither side may sign twice. Any mismatch is rejected with `ERR_SIGNATORY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/signatory_identity_mismatch
    """
    ctx = build_documented_transfer()
    pl2 = create_party("LANDLORD", "Landlord Two LLC", 9000)
    ps2 = create_party("SUBTENANT", "SubTwo Corp", 7000)
    ra_id = ctx["ra_id"]

    resp1 = api.sign_recognition_agreement(
        ra_id, {"signatory": "LANDLORD"}, make_landlord_headers(pl2["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_SIGNATORY_MISMATCH, 403)

    resp2 = api.sign_recognition_agreement(
        ra_id, {"signatory": "COUNTERPARTY"}, make_subtenant_headers(ps2["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_SIGNATORY_MISMATCH, 403)

    recognition = validate_success(api.get_recognition_agreement(ra_id, B1), 200)
    assert recognition["status"] == "DRAFTED"


def test_lattice_counterparty_first(api):
    """PRD §3.7: "Either side may sign first: a `signatory` of `LANDLORD` from the lease's landlord of record, or `COUNTERPARTY` from the transfer's counterparty, each identity-checked per §2.9. The first signature moves the agreement from `DRAFTED` to `PARTIALLY_SIGNED` and stamps `landlord_signed_at` or `counterparty_signed_at` according to the signing side."

    Design: Difficulty/non_linear_state_machine/recognition_agreement_two_sided_signature_lattice
    """
    ctx = build_documented_transfer()
    ra_id = ctx["ra_id"]

    first = sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])
    assert first["status"] == "PARTIALLY_SIGNED"
    assert first["counterparty_signed_at"] is not None
    assert first["landlord_signed_at"] is None

    second = sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    assert second["status"] == "FULLY_EXECUTED"
    assert second["landlord_signed_at"] is not None

    assert get_transfer(ctx["transfer"]["id"])["status"] == "EFFECTIVE"
    instrument = validate_success(api.get_sublease_agreement(ctx["sa_id"], B1), 200)
    assert instrument["status"] == "RECOGNIZED"


def test_lattice_landlord_first(api):
    """PRD §3.7: "Either side may sign first: a `signatory` of `LANDLORD` from the lease's landlord of record, or `COUNTERPARTY` from the transfer's counterparty, each identity-checked per §2.9. The first signature moves the agreement from `DRAFTED` to `PARTIALLY_SIGNED` and stamps `landlord_signed_at` or `counterparty_signed_at` according to the signing side. The second signature, from the opposite side, moves it from `PARTIALLY_SIGNED` to `FULLY_EXECUTED` and stamps the remaining signature field"

    Design: Difficulty/non_linear_state_machine/recognition_agreement_two_sided_signature_lattice
    """
    ctx = build_documented_transfer()
    ra_id = ctx["ra_id"]

    first = sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    assert first["status"] == "PARTIALLY_SIGNED"
    assert first["landlord_signed_at"] is not None
    assert first["counterparty_signed_at"] is None

    second = sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])
    assert second["status"] == "FULLY_EXECUTED"
    assert second["counterparty_signed_at"] is not None

    assert get_transfer(ctx["transfer"]["id"])["status"] == "EFFECTIVE"
    instrument = validate_success(api.get_sublease_agreement(ctx["sa_id"], B1), 200)
    assert instrument["status"] == "RECOGNIZED"


def test_three_hop_cascade_on_second_signature(api):
    """PRD §3.7: "Full execution cascades two hops: the transfer moves `DOCUMENTED → EFFECTIVE` with `effective_at` stamped and the lease's `open_transfer_count` decremented and `version` incremented, and — for a sublease only — the instrument moves `EXECUTED → RECOGNIZED`."

    Design: Difficulty/transitive_cascade/recognition_signature_three_hop_cascade
    """
    ctx = build_documented_transfer()
    ra_id = ctx["ra_id"]
    sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 1

    sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])

    recognition = validate_success(api.get_recognition_agreement(ra_id, B1), 200)
    assert recognition["status"] == "FULLY_EXECUTED", "hop 1: the agreement completes"

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer["status"] == "EFFECTIVE", "hop 2: the transfer advances"
    assert transfer["effective_at"] is not None

    instrument = validate_success(api.get_sublease_agreement(ctx["sa_id"], B1), 200)
    assert instrument["status"] == "RECOGNIZED", "hop 3a: the instrument follows"

    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 0, "hop 3b: the lease counter is released"


def test_cascade_dormant_until_second_signature(api):
    """PRD §3.7: "The first signature moves the agreement from `DRAFTED` to `PARTIALLY_SIGNED` and stamps `landlord_signed_at` or `counterparty_signed_at` according to the signing side. The second signature, from the opposite side, moves it from `PARTIALLY_SIGNED` to `FULLY_EXECUTED` and stamps the remaining signature field"

    Design: Difficulty/transitive_cascade/recognition_signature_three_hop_cascade
    """
    ctx = build_documented_transfer()
    ra_id = ctx["ra_id"]
    lease_v_pre = get_lease(ctx["lease"]["id"])["version"]

    sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    assert get_transfer(ctx["transfer"]["id"])["status"] == "DOCUMENTED", (
        "no cascade before the second signature"
    )
    instrument = validate_success(api.get_sublease_agreement(ctx["sa_id"], B1), 200)
    assert instrument["status"] == "EXECUTED"
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 1

    sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])
    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 0
    assert lease["version"] == lease_v_pre + 1, (
        "effectiveness increments the lease version exactly once"
    )


def test_cascading_side_effect_chain_end_to_end(api):
    """PRD §3.7: "Either side may sign first: a `signatory` of `LANDLORD` from the lease's landlord of record, or `COUNTERPARTY` from the transfer's counterparty, each identity-checked per §2.9."
    PRD §3.7: "Full execution cascades two hops: the transfer moves `DOCUMENTED → EFFECTIVE` with `effective_at` stamped and the lease's `open_transfer_count` decremented and `version` incremented, and — for a sublease only — the instrument moves `EXECUTED → RECOGNIZED`."

    Design: Corner/cross_cutting_layers/cascading_side_effect_chain_end_to_end
    """
    ctx = build_documented_transfer()
    ra_id = ctx["ra_id"]

    first = sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])
    assert first["status"] == "PARTIALLY_SIGNED"
    assert first["counterparty_signed_at"] is not None
    assert first["landlord_signed_at"] is None

    second = sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    assert second["status"] == "FULLY_EXECUTED"
    assert get_transfer(ctx["transfer"]["id"])["status"] == "EFFECTIVE"
    instrument = validate_success(api.get_sublease_agreement(ctx["sa_id"], B1), 200)
    assert instrument["status"] == "RECOGNIZED", (
        "reversed signature order still converges through the cascade"
    )


def test_withdraw_from_documented_compensates(api):
    """PRD §3.9: "From `DOCUMENTED`, withdrawal is possible only while the recognition agreement has not reached `FULLY_EXECUTED` — an executed recognition locks the transfer, and withdrawal after effectiveness is impossible — and it triggers the full compensation cascade: the drafted or partially-signed recognition agreement flips to `VOIDED`, an `EXECUTED` sublease instrument flips to `TERMINATED`, and every restoration obligation of the transfer in `OPEN` or `ESCROW_POSTED` flips to `WAIVED`."

    Design: Corner/state_machines/withdraw_from_documented_compensates_instrument_recognition_restoration
    """
    ctx = build_conditional_grant(conditions=[
        {"condition_kind": "RESTORATION_REQUIRED", "detail": "Restore demising walls"},
    ])
    respond_condition(ctx["conditions"][0]["id"], ctx["pt"]["id"], "ACCEPTED")
    receipt = document_transfer(
        ctx["transfer"]["id"],
        restoration_allocations=[{"responsible_party": "SUBTENANT_OR_ASSIGNEE",
                                  "escrow_amount_cents": 2500000}],
    )
    ra_id = receipt["recognition_agreement_id"]
    sa_id = receipt["sublease_agreement_id"]

    withdrawn = validate_success(
        api.withdraw_transfer_request(ctx["transfer"]["id"], B1), 200,
    )
    assert withdrawn["status"] == "WITHDRAWN"

    recognition = validate_success(api.get_recognition_agreement(ra_id, B1), 200)
    assert recognition["status"] == "VOIDED"

    instrument = validate_success(api.get_sublease_agreement(sa_id, B1), 200)
    assert instrument["status"] == "TERMINATED"

    obligations, _ = validate_paginated(
        api.list_transfer_restoration_obligations(ctx["transfer"]["id"], B1)
    )
    assert len(obligations) == 1
    assert obligations[0]["status"] == "WAIVED"

    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 0
