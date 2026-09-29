"""
Read-your-writes: the signing response and the first read of every row it touched
tell the same story, with no settling window in between.
"""

from test_helpers import (
    ApiClient,
    BoothStatus,
    FloorPosture,
    PriorityTier,
    SpaceContractStatus,
    factories as f,
    fixtures as fx,
    make_exhibitor_headers,
    make_sales_rep_headers,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)

REP = make_sales_rep_headers("u_sr_1")


def _hold_ready_to_sign(client: ApiClient) -> dict:
    """A 400 sqft premium hold priced and waiting, on a 600 sqft floor."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    booth_id = env["booth_by_number"]["A100"]["id"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example",
                          consecutive_years=6, headers=fx.SALES_REP_HEADERS)
    contract = fx.offered_contract(client, show_id, nordic["id"], 400, [booth_id],
                                  headers=REP, premium_placement_requested=True)
    assert fx.read_show(client, show_id)["sellable_booth_sqft"] == 600
    assert contract["invoice_total_cents"] == 1556280
    assert contract["min_deposit_cents"] == 389070
    env.update({"show_id": show_id, "booth_id": booth_id, "nordic": nordic,
                "nordic_headers": make_exhibitor_headers(nordic["id"]),
                "contract": contract,
                "pinned_version": fx.show_version(client, show_id)})
    return env


def test_the_signing_response_already_carries_its_own_settled_fields(
    client: ApiClient,
):
    """
    Nothing about the contract needs a follow-up call: the status, the frozen
    invoice and the earned points are all in the body that answered the write.

    "A successful signature moves the contract `OFFERED → SIGNED` and freezes its
    commercial terms: `space_fee_cents`, `volume_tier_pct`, `bundle_discount_pct`,
    `bundle_discount_cents` and `invoice_total_cents` are held at their current
    values and are not repriced afterwards."  "`points_awarded` is written as that
    assigned footage divided by one hundred with the remainder discarded, multiplied
    by two, and is added to the exhibitor's space-point base"

    Design: Corner/consistency_model/every_derived_field_is_already_settled_in_the_writing_response
    """
    env = _hold_ready_to_sign(client)

    response = validate_success(
        client.sign_space_contract(
            env["contract"]["id"],
            f.sign_payload(env["pinned_version"], 389070),
            env["nordic_headers"],
        )
    )
    assert response["status"] == SpaceContractStatus.SIGNED
    assert response["invoice_total_cents"] == 1556280
    assert response["points_awarded"] == 8
    assert response["assigned_net_sqft"] == 400
    assert response["deposit_paid_cents"] == 389070
    assert response["signed_at"] is not None
    assert response["signed_at"].startswith("2026-08-15T00:00:00")

    reread = fx.read_contract(client, env["contract"]["id"])
    for field in ("status", "invoice_total_cents", "points_awarded",
                  "assigned_net_sqft", "deposit_paid_cents", "signed_at",
                  "space_fee_cents", "volume_tier_pct", "bundle_discount_pct",
                  "bundle_discount_cents", "version"):
        assert reread[field] == response[field]


def test_the_first_read_of_every_touched_row_agrees_with_that_response(
    client: ApiClient,
):
    """
    One read each of the show, the booth and the exhibitor, taken immediately after
    the signature, and every derived number is already final.

    "Aggregates are never lazily derived at read time. Whenever a write changes a
    child row that feeds a parent's ledger, the parent's ledger fields are rewritten
    in the same request and the parent's `version` is incremented."  "The show's
    `assigned_net_sqft`, `held_net_sqft`, `committed_ratio_pct` and `floor_posture`
    are recomputed, and the contract's, the exhibitor's and the show's `version` are
    each incremented."  "The certified variant looks only at history, and it decays.
    Its contract set is the exhibitor's space contracts whose `status` is
    `CLOSED_OUT` and whose show is `CLOSED`."

    Design: Corner/consistency_model/every_derived_field_is_already_settled_in_the_writing_response
    """
    env = _hold_ready_to_sign(client)
    contract_id = env["contract"]["id"]

    validate_success(
        client.sign_space_contract(
            contract_id, f.sign_payload(env["pinned_version"], 389070),
            env["nordic_headers"],
        )
    )

    show = fx.read_show(client, env["show_id"])
    assert show["assigned_net_sqft"] == 400
    assert show["held_net_sqft"] == 0
    assert show["available_net_sqft"] == 200
    assert show["committed_ratio_pct"] == 67
    assert show["floor_posture"] == FloorPosture.OPEN
    assert show["version"] == env["pinned_version"] + 1

    booth = fx.read_booth(client, env["booth_id"])
    assert booth["status"] == BoothStatus.ASSIGNED
    assert booth["space_contract_id"] == contract_id

    exhibitor = fx.read_exhibitor(client, env["nordic"]["id"])
    assert exhibitor["space_points_provisional"] == 8
    assert exhibitor["provisional_priority_points"] == 8
    assert exhibitor["priority_tier"] == PriorityTier.BRONZE
    assert exhibitor["space_points_certified"] == 0
    assert exhibitor["certified_priority_points"] == 0
