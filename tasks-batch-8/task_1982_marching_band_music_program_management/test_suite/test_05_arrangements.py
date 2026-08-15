"""Music library: quote/approve/purchase lifecycle under segregation of duties,
the music budget gate, and clock-driven license expiry."""
from test_helpers import (
    TREASURER_HEADERS,
    ApiErrorId,
    advance_clock,
    approve_arrangement,
    create_arrangement,
    create_open_program,
    get_program,
    make_assistant_headers,
    make_director_headers,
    purchase_arrangement,
    validate_error,
    validate_success,
)

TREASURER = TREASURER_HEADERS


def test_arrangement_lifecycle_spend_and_clock_expiry(api, reader_headers):
    """PRD §3.5: "On approval the acting identifier is recorded as `approver_user_id` and the arrangement moves to `APPROVED`." PRD §3.5: "On purchase the arrangement moves to `LICENSED_ACTIVE` and `music_spent_cents` increases by `cost_cents`." PRD §3.5: "Licenses expire with the clock: when the logical clock passes `rights_end`, the arrangement moves from `LICENSED_ACTIVE` to `EXPIRED`, evaluated lazily on clock set and on read; expiry does not refund anything, and the spent aggregate is unchanged because the money is already gone."

    Design: Corner/state_machines/arrangement_lifecycle_happy_path_and_budget_spend
    """
    program = create_open_program(season_name="AR")  # music budget 100000
    arrangement = create_arrangement(
        program["id"], make_assistant_headers("asst-1"), title="Show Opener",
        arranger="J. Smith", license_type="CUSTOM_ARRANGEMENT",
        cost_cents=30000, rights_end="2026-09-01T00:00:00Z")
    assert arrangement["status"] == "QUOTED"
    assert arrangement["creator_user_id"] == "asst-1"

    approved = approve_arrangement(arrangement["id"],
                                   make_director_headers("dir-1"))
    assert approved["status"] == "APPROVED"
    assert approved["approver_user_id"] == "dir-1"

    purchased = purchase_arrangement(approved["id"])
    assert purchased["status"] == "LICENSED_ACTIVE"
    assert get_program(program["id"])["music_spent_cents"] == 30000

    advance_clock("2026-09-02T00:00:00Z")
    expired = validate_success(api.get_arrangement(arrangement["id"],
                                                   reader_headers))
    assert expired["status"] == "EXPIRED"
    assert get_program(program["id"])["music_spent_cents"] == 30000, (
        "expiry does not refund; the money is already gone")


def test_quoted_and_approved_arrangements_do_not_spend(api):
    """PRD §3.1: "The spending aggregates are pure derived values: `music_spent_cents` is the sum of `cost_cents` over the program's arrangements in `LICENSED_ACTIVE` or `EXPIRED` status, and `repair_spent_cents` is the sum of `repair_cost_cents` over all completed maintenance calls for the program's instruments." PRD §3.5: "On purchase the arrangement moves to `LICENSED_ACTIVE` and `music_spent_cents` increases by `cost_cents`."

    Design: Corner/calculations/music_budget_input_set_excludes_quoted
    """
    program = create_open_program(season_name="MB", music_budget_cents=40000)
    arrangement = create_arrangement(
        program["id"], make_director_headers("dir-1"), title="A", arranger="X",
        license_type="STANDARD", cost_cents=35000,
        rights_end="2026-12-01T00:00:00Z")
    assert get_program(program["id"])["music_spent_cents"] == 0, (
        "QUOTED is excluded from the spent aggregate")

    approved = approve_arrangement(arrangement["id"],
                                   make_director_headers("dir-2"))
    assert approved["status"] == "APPROVED"
    assert get_program(program["id"])["music_spent_cents"] == 0, (
        "APPROVED is still excluded from the spent aggregate")

    purchase_arrangement(approved["id"])
    assert get_program(program["id"])["music_spent_cents"] == 35000


def test_music_budget_equality_allowed_one_cent_over_rejected(api):
    """PRD §3.5: "A `BoosterTreasurer` may purchase an `APPROVED` arrangement (else `ERR_ARRANGEMENT_NOT_APPROVED`), but only while the program's `music_spent_cents` plus this arrangement's `cost_cents` does not exceed `music_budget_cents` — equality is permitted, overshoot rejected with `ERR_MUSIC_BUDGET_EXCEEDED` (HTTP 402)."

    Design: Corner/calculations/music_budget_equality_allowed_over_rejected
    """
    program = create_open_program(season_name="MB2", music_budget_cents=40000)
    creator = make_director_headers("dir-1")
    approver = make_director_headers("dir-2")

    arr_a = create_arrangement(program["id"], creator, title="A", arranger="X",
                               cost_cents=35000, rights_end="2026-12-01T00:00:00Z")
    purchase_arrangement(approve_arrangement(arr_a["id"], approver)["id"])
    assert get_program(program["id"])["music_spent_cents"] == 35000

    arr_b = create_arrangement(program["id"], creator, title="B", arranger="X",
                               cost_cents=5000, rights_end="2026-12-01T00:00:00Z")
    purchased_b = purchase_arrangement(
        approve_arrangement(arr_b["id"], approver)["id"])
    assert purchased_b["status"] == "LICENSED_ACTIVE", (
        "35000 + 5000 == budget: equality is permitted")
    assert get_program(program["id"])["music_spent_cents"] == 40000

    arr_c = create_arrangement(program["id"], creator, title="C", arranger="X",
                               cost_cents=40001, rights_end="2026-12-01T00:00:00Z")
    approve_arrangement(arr_c["id"], approver)
    rejected = api.purchase_arrangement(arr_c["id"], TREASURER)
    validate_error(rejected, ApiErrorId.ERR_MUSIC_BUDGET_EXCEEDED)
    assert get_program(program["id"])["music_spent_cents"] == 40000


def test_creator_cannot_approve_own_quote(api):
    """PRD §3.5: "A `BandDirector` may approve a `QUOTED` arrangement (else `ERR_ARRANGEMENT_NOT_QUOTED`), but the approver's `X-User-ID` must differ from `creator_user_id` — self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On approval the acting identifier is recorded as `approver_user_id` and the arrangement moves to `APPROVED`."

    Design: Corner/validations/arrangement_approve_segregation_of_duties
    """
    program = create_open_program(season_name="SD")
    arrangement = create_arrangement(
        program["id"], make_director_headers("dir-1"), title="SOD", arranger="X",
        license_type="STANDARD", cost_cents=10000,
        rights_end="2026-12-01T00:00:00Z")
    assert arrangement["creator_user_id"] == "dir-1"

    self_approval = api.approve_arrangement(arrangement["id"],
                                            make_director_headers("dir-1"))
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = approve_arrangement(arrangement["id"],
                                   make_director_headers("dir-2"))
    assert approved["status"] == "APPROVED"
    assert approved["approver_user_id"] == "dir-2"
