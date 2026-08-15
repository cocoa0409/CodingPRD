"""Helmet distribution: low-stock boundary (queue A) and helmet corner cases
(queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_part, make_helmet_part, restock_part, make_participant,
    make_hours_met_participant,
    TEST_USERS,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def test_low_stock_equality_flag():
    """PRD §2.8: "`low_stock` is true whenever `quantity_on_hand` is less than
    or equal to `reorder_threshold` — equality counts as low."

    Design: Difficulty/boundary_precision_check/low_stock_equality_flag
    """
    hp = make_helmet_part(name="Helmet M", helmet_size="M", unit_cost_cents=1500,
                          reorder_threshold=2)
    assert hp["low_stock"] is True  # 0 <= 2
    stocked = restock_part(hp["id"], 3)
    assert stocked["quantity_on_hand"] == 3
    assert stocked["low_stock"] is False  # 3 > 2

    validate_success(
        api_client.create_helmet_distribution(
            {"helmet_part_id": hp["id"], "recipient_kind": "COMMUNITY",
             "recipient_name": "Walk-in W"},
            COORD,
        ),
        expected_status=201,
    )
    after = validate_success(api_client.get_part(hp["id"], COORD))
    assert after["quantity_on_hand"] == 2
    assert after["low_stock"] is True  # 2 <= 2: equality is low


def test_low_stock_flag_roundtrip_on_restock():
    """PRD §2.8: "`low_stock` is true whenever `quantity_on_hand` is less than
    or equal to `reorder_threshold` — equality counts as low."

    Design: Difficulty/boundary_precision_check/low_stock_equality_flag
    """
    p = make_part(name="Cable", category="BRAKES", unit_cost_cents=100,
                  reorder_threshold=1)
    assert p["low_stock"] is True  # 0 <= 1
    stocked = restock_part(p["id"], 1)
    assert stocked["quantity_on_hand"] == 1
    assert stocked["low_stock"] is True  # 1 <= 1: equality is low
    more = restock_part(p["id"], 1)
    assert more["quantity_on_hand"] == 2
    assert more["low_stock"] is False  # 2 > 1


def test_helmet_part_size_conditional_constraint():
    """PRD §3.3: "when `category` is `HELMET`, a `helmet_size` of `XS`, `S`,
    `M`, `L`, or `XL` is required, and when the category is anything else,
    `helmet_size` must be absent — either violation is rejected with
    `ERR_HELMET_SIZE_REQUIRED`."

    Design: Corner/entities/helmet_part_size_conditional_constraint
    """
    r1 = api_client.create_part(
        {"name": "Helmet NoSize", "category": "HELMET", "unit_cost_cents": 1500},
        COORD,
    )
    validate_error(r1, ApiErrorId.ERR_HELMET_SIZE_REQUIRED)
    r2 = api_client.create_part(
        {"name": "Brake w/ size", "category": "BRAKES", "helmet_size": "M"},
        COORD,
    )
    validate_error(r2, ApiErrorId.ERR_HELMET_SIZE_REQUIRED)
    ok = validate_success(
        api_client.create_part(
            {"name": "Helmet S", "category": "HELMET", "helmet_size": "S"}, COORD
        ),
        expected_status=201,
    )
    assert ok["quantity_on_hand"] == 0
    # 0 <= default reorder_threshold 0
    assert ok["low_stock"] is True


def test_helmet_recipient_reference_mismatch():
    """PRD §3.11: "The `recipient_kind` field is one of `EARN_A_BIKE_GRADUATE`,
    `SALE_BUYER`, `GIVEAWAY_RECIPIENT`, or `COMMUNITY`, and exactly the matching
    reference must be present with the others absent, else
    `ERR_RECIPIENT_REFERENCE_MISMATCH`".

    Design: Corner/validations/helmet_recipient_reference_mismatch
    """
    hp = make_helmet_part(name="Helmet X", helmet_size="XL", unit_cost_cents=1500)
    restock_part(hp["id"], 5)
    p = make_participant(full_name="P HM", contact_email="phm@x.org",
                         age_group="ADULT")
    r1 = api_client.create_helmet_distribution(
        {"helmet_part_id": hp["id"], "recipient_kind": "SALE_BUYER",
         "participant_id": p["id"]},
        COORD,
    )
    validate_error(r1, ApiErrorId.ERR_RECIPIENT_REFERENCE_MISMATCH)
    r2 = api_client.create_helmet_distribution(
        {"helmet_part_id": hp["id"], "recipient_kind": "EARN_A_BIKE_GRADUATE"},
        COORD,
    )
    validate_error(r2, ApiErrorId.ERR_RECIPIENT_REFERENCE_MISMATCH)
    r3 = api_client.create_helmet_distribution(
        {"helmet_part_id": hp["id"], "recipient_kind": "COMMUNITY"},
        COORD,
    )
    validate_error(r3, ApiErrorId.ERR_RECIPIENT_REFERENCE_MISMATCH)
    after = validate_success(api_client.get_part(hp["id"], COORD))
    assert after["quantity_on_hand"] == 5


def test_not_a_helmet_sku_rejected():
    """PRD §3.11: "Each distribution names a `helmet_part_id` referencing a part
    whose `category` is `HELMET` — any other SKU is rejected with
    `ERR_NOT_A_HELMET_SKU`".

    Design: Corner/validations/not_a_helmet_sku_rejected
    """
    p = make_part(name="Brake set", category="BRAKES", unit_cost_cents=700)
    restock_part(p["id"], 3)
    r = api_client.create_helmet_distribution(
        {"helmet_part_id": p["id"], "recipient_kind": "COMMUNITY",
         "recipient_name": "W"},
        COORD,
    )
    validate_error(r, ApiErrorId.ERR_NOT_A_HELMET_SKU)
    after = validate_success(api_client.get_part(p["id"], COORD))
    assert after["quantity_on_hand"] == 3


def test_helmet_out_of_stock_boundary():
    """PRD §3.11: "decrements that SKU's `quantity_on_hand` by 1, bumping the
    part's `version` and recomputing `low_stock`. A distribution when the SKU's
    stock is zero is rejected with `ERR_HELMET_OUT_OF_STOCK`."

    Design: Corner/validations/helmet_out_of_stock_boundary
    """
    hp = make_helmet_part(name="Helmet Z", helmet_size="M", unit_cost_cents=1500)
    restock_part(hp["id"], 1)
    validate_success(
        api_client.create_helmet_distribution(
            {"helmet_part_id": hp["id"], "recipient_kind": "COMMUNITY",
             "recipient_name": "First"},
            COORD,
        ),
        expected_status=201,
    )
    r = api_client.create_helmet_distribution(
        {"helmet_part_id": hp["id"], "recipient_kind": "COMMUNITY",
         "recipient_name": "Second"},
        COORD,
    )
    validate_error(r, ApiErrorId.ERR_HELMET_OUT_OF_STOCK)
    after = validate_success(api_client.get_part(hp["id"], COORD))
    assert after["quantity_on_hand"] == 0
