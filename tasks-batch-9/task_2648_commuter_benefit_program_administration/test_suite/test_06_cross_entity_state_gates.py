"""Gates whose verdict lives on a different entity than the one being written.

Two such gates are exercised here, each with the blocked case and the permitted
case that proves the referenced entity's state is the only thing deciding the
outcome:

* adding a media line depends on the posture of the procurement batch it is
  filed into, not on anything about the line itself, and
* filing an election depends on the sponsoring employer's program posture, an
  entity the election payload never names.

Every test builds its own program from scratch through the documented endpoints,
because the service is restarted against an empty database before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import PROGRAM_ADMIN, fixtures as fx
from test_helpers.api_errors import (
    ERR_EMPLOYER_PROGRAM_NOT_ACTIVE,
    ERR_ORDER_BATCH_NOT_OPEN,
    ERR_STALE_ACCOUNT_VERSION,
)
from test_helpers.assertions import assert_election_axes, assert_unchanged
from test_helpers.constants import REGION_AUS
from test_helpers.factories import election_payload, media_order_payload
from test_helpers.test_users import make_order_desk_headers

DESK = "desk-gate"
COVERAGE_START = "2026-08-01T00:00:00Z"
COVERAGE_END = "2026-08-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Composite state builders used by the tests in this module.
# ---------------------------------------------------------------------------
def _build_batch_gate_program(api) -> dict:
    """An ACTIVE Austin employer, one catalogue product, two employees each with
    a PENDING election entitled to one media unit, and one OPEN procurement batch
    against that same election window.

    Two employees rather than two elections for one employee, so a line filed for
    the second employee can never supersede the first employee's line.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "TRANSIT_PASS",
                "monthly_exclusion_limit_cents": 30000,
            }
        ],
        legal_name="Austin Batch Gate Co",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    media = fx.make_transit_media(
        api,
        region_code=REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=1000,
        sku="AUS-GATE",
        requires_physical_fulfillment=True,
    )
    window = fx.make_open_window(api, employer["id"], PROGRAM_ADMIN)

    elections = []
    for index in (1, 2):
        enrolled = fx.make_enrolled_employee(
            api,
            employer["id"],
            category["id"],
            PROGRAM_ADMIN,
            external_ref=f"AUS-G{index}",
            work_region_code=REGION_AUS,
        )
        elections.append(
            fx.make_election(
                api,
                enrolled["employee"]["id"],
                window["id"],
                category["id"],
                enrolled["account"]["id"],
                pretax_amount_cents=1000,
                transit_media_id=media["id"],
                media_quantity=1,
            )
        )

    batch = fx.make_open_batch(api, window["id"], REGION_AUS, DESK)
    return {
        "employer": employer,
        "category": category,
        "media": media,
        "window": window,
        "elections": elections,
        "batch": batch,
    }


def _line_body(api, election_id: str, media_id: str, batch_id: str) -> dict:
    """The media line body under test, always carrying a freshly read election
    version so no concurrency token can be the reason a create is refused."""
    return media_order_payload(
        election_id,
        media_id,
        batch_id,
        fx.current_election_version(api, election_id),
        quantity=1,
        coverage_start_at=COVERAGE_START,
        coverage_end_at=COVERAGE_END,
    )


def _build_capped_program(api) -> dict:
    """An ACTIVE Austin employer whose program cap of 25000 cents is lower than
    the single 30000-cent election already pending in its August window, plus a
    second, adjacent September window that is also OPEN.

    Locking August therefore breaches the cap through the funding cascade and
    drives the employer into its terminal SUSPENDED posture, while September's
    calendar slot and the employee's account are left exactly as they were.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "TRANSIT_PASS",
                "monthly_exclusion_limit_cents": 30000,
            }
        ],
        legal_name="Austin Cap Gate Co",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        spill_policy="SPILL_TO_POSTTAX",
        program_cap_cents=25000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    enrolled = fx.make_enrolled_employee(
        api,
        employer["id"],
        category["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-CG1",
        work_region_code=REGION_AUS,
    )
    august = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )
    september = fx.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-09",
        opens_at="2026-08-20T00:00:00Z",
        cutoff_at="2026-09-20T00:00:00Z",
    )
    return {
        "employer": employer,
        "category": category,
        "employee": enrolled["employee"],
        "account": enrolled["account"],
        "august": august,
        "september": september,
    }


def _september_election_body(api, program: dict) -> dict:
    """The September election body under test, always carrying a freshly read
    account version so no concurrency token can be the reason it is refused."""
    return election_payload(
        program["employee"]["id"],
        program["september"]["id"],
        program["category"]["id"],
        fx.current_account_version(api, program["account"]["id"]),
        pretax_amount_cents=5000,
        posttax_amount_cents=0,
    )


# ---------------------------------------------------------------------------
# Gate 1: the procurement batch's posture decides whether a media line lands.
# ---------------------------------------------------------------------------
def test_01_media_line_accepted_while_its_procurement_batch_is_open(api):
    """A media line filed into a batch that is still OPEN is accepted.

    This is the permitted half of the gate: the line body, the election, the
    catalogue product and the clock are all exactly what the blocked case uses,
    and the batch's OPEN posture is the only reason this create succeeds.

    PRD: "A new batch opens in `status` `OPEN` with `line_count`, `subtotal_cents`, `discount_cents` and `total_cents` all zero and both `sealed_by_user_id` and `released_by_user_id` null, as well as `sealed_at`."
    PRD: "A successful line create opens the row in `status` `PENDING` with `unit_price_cents_snapshot` copied from the catalogue product's current `unit_price_cents`, `tracking_ref` and `undelivered_reason` null, `replacement_count` and `replacement_fee_charged_cents` at zero, and `line_gross_cents`, `line_surcharge_cents` and `line_total_cents` all zero until the batch is priced."
    PRD: "Creating a media line for an election that was waiting therefore advances the election `AWAITING_ORDER → ORDERED`, provided `entitled_media_units` is greater than zero and at least one of the election's media orders is not `CANCELLED`."
    Design: Difficulty/cross_entity_state_dependency/media_order_create_blocked_by_order_batch_sealed_state
    """
    program = _build_batch_gate_program(api)
    batch = program["batch"]
    assert batch["status"] == "OPEN"
    election = program["elections"][0]

    body = _line_body(api, election["id"], program["media"]["id"], batch["id"])
    line = validate_success(
        api.create_media_order(body, make_order_desk_headers(DESK)), 201
    )

    assert line["status"] == "PENDING"
    assert line["order_batch_id"] == batch["id"]
    assert line["election_id"] == election["id"]
    assert line["unit_price_cents_snapshot"] == 1000
    assert line["line_gross_cents"] == 0
    assert line["line_surcharge_cents"] == 0
    assert line["line_total_cents"] == 0
    assert_election_axes(fx.read_election(api, election["id"]), "PENDING", "ORDERED")


def test_02_media_line_refused_once_its_procurement_batch_is_sealed(api):
    """The same media line body is refused after the batch it names is sealed.

    Nothing about the line changes between the two halves of this gate: the
    election is freshly read for its concurrency token, the clock still sits well
    before the window's cutoff, the employer is ACTIVE and the product is ACTIVE.
    Only the batch has left OPEN, and that alone is the rejection.

    PRD: "Batch openness: a media line may only be added to a batch whose `status` is `OPEN`, otherwise `ERR_ORDER_BATCH_NOT_OPEN` (HTTP 409)."
    PRD: "The batch then moves `OPEN → SEALED`, `sealed_by_user_id` records the acting `X-User-ID`, `sealed_at` records the current logical clock instant, and `OrderBatch.version` advances by 1 alongside the `version` of every priced media line."
    PRD: "no line can be added after the seal because the batch has left `OPEN`"
    Design: Difficulty/cross_entity_state_dependency/media_order_create_blocked_by_order_batch_sealed_state
    """
    program = _build_batch_gate_program(api)
    batch = program["batch"]
    first, second = program["elections"]

    # One priced line so the batch is not empty at seal time.
    fx.make_media_order(
        api, first["id"], program["media"]["id"], batch["id"], desk_user_id=DESK
    )
    sealed = validate_success(
        api.seal_order_batch(batch["id"], make_order_desk_headers(DESK)), 200
    )
    assert sealed["status"] == "SEALED"
    assert sealed["sealed_by_user_id"] == DESK
    assert sealed["line_count"] == 1

    body = _line_body(api, second["id"], program["media"]["id"], batch["id"])
    validate_error(
        api.create_media_order(body, make_order_desk_headers(DESK)),
        ERR_ORDER_BATCH_NOT_OPEN,
    )

    # The refused line left no trace on the batch or on its own election.
    after = fx.read_batch(api, batch["id"])
    assert after["line_count"] == 1
    assert after["status"] == "SEALED"
    assert_election_axes(
        fx.read_election(api, second["id"]), "PENDING", "AWAITING_ORDER"
    )


def test_03_same_media_line_body_accepted_in_a_fresh_open_batch(api):
    """The line body refused against the sealed batch is accepted, unchanged,
    against a batch that is OPEN — so the sealed batch's posture, and not the
    line, the election, the product or the calendar, was the whole reason.

    PRD: "Batch openness: a media line may only be added to a batch whose `status` is `OPEN`, otherwise `ERR_ORDER_BATCH_NOT_OPEN` (HTTP 409)."
    PRD: "A successful line create opens the row in `status` `PENDING` with `unit_price_cents_snapshot` copied from the catalogue product's current `unit_price_cents`, `tracking_ref` and `undelivered_reason` null, `replacement_count` and `replacement_fee_charged_cents` at zero, and `line_gross_cents`, `line_surcharge_cents` and `line_total_cents` all zero until the batch is priced."
    PRD: "Creating a media line for an election that was waiting therefore advances the election `AWAITING_ORDER → ORDERED`, provided `entitled_media_units` is greater than zero and at least one of the election's media orders is not `CANCELLED`."
    Design: Difficulty/cross_entity_state_dependency/media_order_create_blocked_by_order_batch_sealed_state
    """
    program = _build_batch_gate_program(api)
    sealed_batch = program["batch"]
    first, second = program["elections"]

    fx.make_media_order(
        api, first["id"], program["media"]["id"], sealed_batch["id"], desk_user_id=DESK
    )
    validate_success(
        api.seal_order_batch(sealed_batch["id"], make_order_desk_headers(DESK)), 200
    )

    refused = _line_body(api, second["id"], program["media"]["id"], sealed_batch["id"])
    validate_error(
        api.create_media_order(refused, make_order_desk_headers(DESK)),
        ERR_ORDER_BATCH_NOT_OPEN,
    )

    fresh_batch = fx.make_open_batch(
        api, program["window"]["id"], REGION_AUS, "desk-gate-two"
    )
    assert fresh_batch["status"] == "OPEN"

    accepted = dict(refused)
    accepted["order_batch_id"] = fresh_batch["id"]
    line = validate_success(
        api.create_media_order(accepted, make_order_desk_headers(DESK)), 201
    )

    assert line["status"] == "PENDING"
    assert line["order_batch_id"] == fresh_batch["id"]
    assert line["election_id"] == second["id"]
    assert line["quantity"] == refused["quantity"]
    assert line["coverage_start_at"] == refused["coverage_start_at"]
    assert line["coverage_end_at"] == refused["coverage_end_at"]
    assert line["unit_price_cents_snapshot"] == 1000
    assert_election_axes(fx.read_election(api, second["id"]), "PENDING", "ORDERED")
    assert fx.read_batch(api, sealed_batch["id"])["status"] == "SEALED"


# ---------------------------------------------------------------------------
# Gate 2: the sponsoring employer's posture decides whether an election lands.
# ---------------------------------------------------------------------------
def test_04_election_filed_while_the_employer_program_is_active(api):
    """An election filed into an OPEN window of an ACTIVE employer is accepted.

    The election payload never names the employer, yet the employer is what the
    gate reads.  Here it reads ACTIVE — the 30000-cent August election is still
    PENDING, so nothing is committed against the 25000-cent program cap — and the
    September election is accepted.

    PRD: "Owning employer program active: the Employer that owns the target resource must have `program_status` of `ACTIVE`, otherwise `ERR_EMPLOYER_PROGRAM_NOT_ACTIVE` (HTTP 409)."
    PRD: "The employer's `total_pretax_committed_cents` is recomputed as the sum of `excluded_amount_cents` over every election whose window belongs to this employer and whose `funding_status` is exactly `FUNDED`."
    PRD: "`excluded_amount_cents` is then the smallest of those four values: the requested `pretax_amount_cents`, the group headroom, the category cap, and the ratio cap."
    PRD: "The new row opens with `funding_status` `PENDING` and `change_count` at zero."
    PRD: "Its `fulfillment_status` is derived immediately: an election created with `media_quantity` of zero, or with the field omitted altogether, opens in `NOT_REQUIRED`, because no media will ever be needed for it"
    Design: Difficulty/cross_entity_state_dependency/election_create_blocked_by_employer_suspended_program_status
    """
    program = _build_capped_program(api)
    fx.make_election(
        api,
        program["employee"]["id"],
        program["august"]["id"],
        program["category"]["id"],
        program["account"]["id"],
        pretax_amount_cents=30000,
        posttax_amount_cents=0,
    )

    employer_before = fx.read_employer(api, program["employer"]["id"])
    assert employer_before["program_status"] == "ACTIVE"
    assert employer_before["total_pretax_committed_cents"] == 0

    body = _september_election_body(api, program)
    election = validate_success(api.create_election(body, PROGRAM_ADMIN), 201)

    assert_election_axes(election, "PENDING", "NOT_REQUIRED")
    assert election["election_window_id"] == program["september"]["id"]
    assert election["excluded_amount_cents"] == 5000
    assert election["posttax_spill_cents"] == 0
    assert election["change_count"] == 0


def test_05_election_refused_after_the_program_cap_breach_suspends_the_employer(api):
    """The identical election body is refused once the August lock has driven the
    employer into SUSPENDED by breaching its program cap.

    The September window is still OPEN, the employee and the account and the
    category are all untouched, and the account version handed in is freshly read.
    The only thing that changed is a state on the employer.

    PRD: "Each re-priced election then lands in one of two postures: `PENDING → HELD` when the electing employee's `substantiation_hold` is true, and `PENDING → FUNDED` otherwise."
    PRD: "The employer's `total_pretax_committed_cents` is recomputed as the sum of `excluded_amount_cents` over every election whose window belongs to this employer and whose `funding_status` is exactly `FUNDED`."
    PRD: "If the recomputed total is **strictly greater** than the employer's `program_cap_cents`, the employer is driven `ACTIVE → SUSPENDED` and `Employer.version` advances by 1."
    PRD: "Owning employer program active: the Employer that owns the target resource must have `program_status` of `ACTIVE`, otherwise `ERR_EMPLOYER_PROGRAM_NOT_ACTIVE` (HTTP 409)."
    PRD: "A new window is created in `status` `SCHEDULED` with `locked_at` null and `election_count` at zero; that counter tracks elections in the window whose `funding_status` is `PENDING`, `HELD`, `FUNDED` or `SETTLED`."
    Design: Difficulty/cross_entity_state_dependency/election_create_blocked_by_employer_suspended_program_status
    """
    program = _build_capped_program(api)
    august_election = fx.make_election(
        api,
        program["employee"]["id"],
        program["august"]["id"],
        program["category"]["id"],
        program["account"]["id"],
        pretax_amount_cents=30000,
        posttax_amount_cents=0,
    )

    locked = validate_success(
        api.lock_election_window(program["august"]["id"], PROGRAM_ADMIN), 200
    )
    assert locked["status"] == "LOCKED"
    assert_election_axes(
        fx.read_election(api, august_election["id"]), "FUNDED", "NOT_REQUIRED"
    )

    employer = fx.read_employer(api, program["employer"]["id"])
    assert employer["total_pretax_committed_cents"] == 30000
    assert employer["program_status"] == "SUSPENDED"

    body = _september_election_body(api, program)
    validate_error(
        api.create_election(body, PROGRAM_ADMIN), ERR_EMPLOYER_PROGRAM_NOT_ACTIVE
    )

    september = fx.read_window(api, program["september"]["id"])
    assert september["status"] == "OPEN"
    assert september["election_count"] == 0


def test_06_suspension_and_not_the_window_or_account_version_is_the_gate(api):
    """The refusal survives a freshly read account version and leaves the
    September window and the election already sitting in it exactly as they were.

    This pins the gate onto the employer alone: the concurrency token is current,
    so the answer is not the stale-version guard; the September window is OPEN and
    still counts its one election, so the answer is not the window's posture; and
    the election already in September never moves, because the cap breach touched
    only the employer and the August rows.

    PRD: "If that value does not equal the account's current `version`, the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD: "Owning employer program active: the Employer that owns the target resource must have `program_status` of `ACTIVE`, otherwise `ERR_EMPLOYER_PROGRAM_NOT_ACTIVE` (HTTP 409)."
    PRD: "Rows a cascade evaluates but does not change are left alone, and their `version` does not move."
    PRD: "A new window is created in `status` `SCHEDULED` with `locked_at` null and `election_count` at zero; that counter tracks elections in the window whose `funding_status` is `PENDING`, `HELD`, `FUNDED` or `SETTLED`."
    PRD: "If the recomputed total is **strictly greater** than the employer's `program_cap_cents`, the employer is driven `ACTIVE → SUSPENDED` and `Employer.version` advances by 1."
    Design: Difficulty/cross_entity_state_dependency/election_create_blocked_by_employer_suspended_program_status
    """
    program = _build_capped_program(api)
    august_election = fx.make_election(
        api,
        program["employee"]["id"],
        program["august"]["id"],
        program["category"]["id"],
        program["account"]["id"],
        pretax_amount_cents=30000,
        posttax_amount_cents=0,
    )
    september_election = validate_success(
        api.create_election(_september_election_body(api, program), PROGRAM_ADMIN), 201
    )

    validate_success(
        api.lock_election_window(program["august"]["id"], PROGRAM_ADMIN), 200
    )
    assert (
        fx.read_employer(api, program["employer"]["id"])["program_status"] == "SUSPENDED"
    )
    assert_election_axes(
        fx.read_election(api, august_election["id"]), "FUNDED", "NOT_REQUIRED"
    )

    # A current token, so the stale-version guard cannot be what answers.
    body = _september_election_body(api, program)
    assert body["expected_account_version"] == fx.current_account_version(
        api, program["account"]["id"]
    )
    error = validate_error(
        api.create_election(body, PROGRAM_ADMIN), ERR_EMPLOYER_PROGRAM_NOT_ACTIVE
    )
    assert error["error_id"] != ERR_STALE_ACCOUNT_VERSION

    september = fx.read_window(api, program["september"]["id"])
    assert september["status"] == "OPEN"
    assert september["election_count"] == 1

    after = fx.read_election(api, september_election["id"])
    assert_unchanged(
        september_election,
        after,
        "funding_status",
        "fulfillment_status",
        "excluded_amount_cents",
        "posttax_spill_cents",
        "change_count",
    )
    assert_election_axes(after, "PENDING", "NOT_REQUIRED")
