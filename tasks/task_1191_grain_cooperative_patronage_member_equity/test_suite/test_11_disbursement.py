"""Disbursement: certificate face-value conservation and immediate
consistency (PRD §2.9, §3.6)."""
from test_helpers import (
    validate_success, api_client,
    setup_under_review_request, approve_request,
    create_redemption_request, submit_request,
    set_clock, TEST_USERS,
)

TREASURER = TEST_USERS["treasurer_headers"]


def _approved_request(ctx, amount, appointment_at):
    """Create + submit + board-approve a RETIREMENT request against the
    context's certificate. Clock is far in the future so every certificate
    is past its holding period and appointment slots are upcoming."""
    member = ctx["member"]
    cert = ctx["certificate"]
    set_clock("2050-01-01T00:00:00Z")
    request = create_redemption_request(
        member["id"], "RETIREMENT", [cert["id"]], amount, appointment_at,
    )
    submitted = submit_request(request["id"], member["id"])
    assert submitted["status"] == "UNDER_REVIEW"
    return approve_request(
        submitted["id"], member["id"], kind="RETIREMENT",
        delegate_id=ctx["delegate"]["id"],
    )


def test_partial_disburse_conserves_face_value(api):
    """PRD §2.9: "For every equity certificate in any status other than
    `REVOKED`, the certificate's `outstanding_cents` plus the sum of all
    disbursements ever made against that certificate must equal its
    `face_value_cents` exactly."
    PRD §3.6: "A certificate paid short of its full outstanding balance moves
    `ACTIVE` → `PARTIALLY_REDEEMED` with its `outstanding_cents` reduced;
    paying the remaining balance moves it to `REDEEMED` with
    `outstanding_cents` zeroed."

    Design: Difficulty/compensating_invariant/certificate_face_value_conservation_across_estate_distribution
    """
    ctx = setup_under_review_request()
    cert = ctx["certificate"]
    face = cert["face_value_cents"]
    assert face > 20000, "setup failed: certificate face too small"
    approved = _approved_request(ctx, 20000, "2050-02-01T10:00:00Z")
    cert_now = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    paid = validate_success(
        api.disburse_redemption(
            approved["id"],
            {"expected_certificate_versions": [cert_now["version"]]},
            TREASURER,
        ),
        200,
    )
    assert paid["status"] == "PAID"
    cert_after = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    assert cert_after["status"] == "PARTIALLY_REDEEMED"
    assert cert_after["outstanding_cents"] + 20000 == face, (
        "Conservation: outstanding + disbursed must equal face value; got "
        f"{cert_after['outstanding_cents']} + 20000 != {face}"
    )


def test_final_disburse_completes_redemption(api):
    """PRD §3.6: "A certificate paid short of its full outstanding balance
    moves `ACTIVE` → `PARTIALLY_REDEEMED` with its `outstanding_cents`
    reduced; paying the remaining balance moves it to `REDEEMED` with
    `outstanding_cents` zeroed."
    PRD §2.9: "For every equity certificate in any status other than
    `REVOKED`, the certificate's `outstanding_cents` plus the sum of all
    disbursements ever made against that certificate must equal its
    `face_value_cents` exactly."

    Design: Difficulty/compensating_invariant/certificate_face_value_conservation_across_estate_distribution
    """
    ctx = setup_under_review_request()
    cert = ctx["certificate"]
    member = ctx["member"]
    face = cert["face_value_cents"]
    assert face > 20000, "setup failed: certificate face too small"
    set_clock("2050-01-01T00:00:00Z")
    # Submit both requests up-front, while the certificate is still ACTIVE;
    # submission requires ACTIVE per PRD §3.6 ("every listed certificate must
    # be owned by the member and in `ACTIVE` status"). The first disbursement
    # will move the certificate ACTIVE → PARTIALLY_REDEEMED, after which the
    # second request can still be approved and disbursed against it.
    first_req = create_redemption_request(
        member["id"], "RETIREMENT", [cert["id"]], 20000,
        "2050-02-01T10:00:00Z",
    )
    submit_request(first_req["id"], member["id"])
    first = approve_request(
        first_req["id"], member["id"], kind="RETIREMENT",
        delegate_id=ctx["delegate"]["id"],
    )
    remainder = face - 20000
    second_req = create_redemption_request(
        member["id"], "RETIREMENT", [cert["id"]], remainder,
        "2050-02-01T11:00:00Z",
    )
    submit_request(second_req["id"], member["id"])
    second = approve_request(
        second_req["id"], member["id"], kind="RETIREMENT",
        delegate_id=ctx["delegate"]["id"],
    )
    cert_now = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    validate_success(
        api.disburse_redemption(
            first["id"],
            {"expected_certificate_versions": [cert_now["version"]]},
            TREASURER,
        ),
        200,
    )
    cert_mid = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    paid = validate_success(
        api.disburse_redemption(
            second["id"],
            {"expected_certificate_versions": [cert_mid["version"]]},
            TREASURER,
        ),
        200,
    )
    assert paid["status"] == "PAID"
    cert_final = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    assert cert_final["status"] == "REDEEMED"
    assert cert_final["outstanding_cents"] == 0
    # Conservation across both disbursements: 0 + (20000 + remainder) == face.
    assert cert_final["outstanding_cents"] + 20000 + remainder == face


def test_disburse_immediately_visible(api):
    """PRD §3.6: "A certificate paid short of its full outstanding balance
    moves `ACTIVE` → `PARTIALLY_REDEEMED` with its `outstanding_cents`
    reduced; paying the remaining balance moves it to `REDEEMED` with
    `outstanding_cents` zeroed."
    PRD §2.5: "Derived-field recomputation is a mutation. When a settlement
    bumps a member's cumulative retains, when a disbursement reduces a
    member's equity totals, or when a cycle's redeemed total advances, the
    owning resource's `updated_at` refreshes and its `version` increments."

    Design: Corner/consistency_model/certificate_balance_reflects_disburse_immediately
    """
    ctx = setup_under_review_request(
        net_margin_cents=100000, retained_reserve_pct=0.10,
        qualified_payout_pct=0.20, gross_bushels=1000,
    )
    cert = ctx["certificate"]
    pre = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    assert pre["outstanding_cents"] > 5000, "setup failed: outstanding too small"
    approved = _approved_request(ctx, 5000, "2050-02-01T10:00:00Z")
    paid = validate_success(
        api.disburse_redemption(
            approved["id"],
            {"expected_certificate_versions": [pre["version"]]},
            TREASURER,
        ),
        200,
    )
    assert paid["status"] == "PAID"
    after = validate_success(
        api_client.get_certificate(cert["id"], TREASURER), 200,
    )
    assert after["outstanding_cents"] == pre["outstanding_cents"] - 5000, (
        "Immediate consistency: the read after disburse must reflect the "
        f"drawdown; got {after['outstanding_cents']} (pre "
        f"{pre['outstanding_cents']})"
    )
    assert after["status"] == "PARTIALLY_REDEEMED"
