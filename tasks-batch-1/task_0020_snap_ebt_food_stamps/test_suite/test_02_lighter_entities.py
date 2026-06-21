"""PRD §2.4 lighter-entity tests: EligibleItemCategory and SystemClock.
Both carry only id + created_at — no updated_at, no version.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_eligible_item_category_payload,
    set_clock,
)

PA = TEST_USERS["policy_admin_headers"]


def test_eligible_item_category_has_no_version_field(api):
    """Creating an EligibleItemCategory returns a response without `version`
    and without `updated_at`. PRD §2.4 deliberately excludes both bookkeeping
    fields for this entity class.

    PRD §2.4: "Two entities are deliberately lighter. `EligibleItemCategory`
    and `SystemClock` carry only `id` and `created_at`; they have no
    `updated_at` and no `version`."
    PRD §3.8: "Categories such as `FRESH_PRODUCE`, `DAIRY`, `MEAT`, and
    `BREAD` are eligible; `TOBACCO`, `ALCOHOL`, `HOT_PREPARED`, and
    `NON_FOOD` are not."

    Design: Corner/entities/eligible_item_category_has_no_version_field
    """
    resp = api.create_eligible_item_category(
        create_eligible_item_category_payload(
            code="TOBACCO", name="Tobacco", eligible=False),
        PA,
    )
    cat = validate_success(resp, 201)
    assert "version" not in cat, \
        f"EligibleItemCategory must not expose 'version' (PRD §2.4); got {cat.get('version')!r}"
    assert "updated_at" not in cat, \
        f"EligibleItemCategory must not expose 'updated_at' (PRD §2.4); got {cat.get('updated_at')!r}"
    assert cat["eligible"] is False, \
        f"category was created with eligible=False, response shows {cat['eligible']!r}"


def test_clock_get_returns_current_utc(api):
    """After setting the clock, GET /snap/_clock returns the same instant in
    SystemClock.current_utc. PRD §3.10 names both capabilities and the field.

    PRD §3.10: "The system's logical wall clock is represented by a
    `SystemClock` resource with a single `current_utc` field."
    PRD §3.10: "A `PolicyAdmin` may set it via a test-driving capability that
    accepts a single `to_iso8601` value in the request body and sets
    `SystemClock.current_utc` to that instant; advancing the clock can also
    fire deferred system transitions"
    PRD §3.10: "The current clock value is also readable."

    Design: Corner/endpoints/clock_get_returns_current_utc
    """
    set_clock("2026-12-25T00:00:00.000Z")
    resp = api.get_clock(PA)
    data = validate_success(resp, 200)
    # PRD §2.7 mandates ISO 8601 with three fractional digits, but accept
    # the two canonical normalisations of midnight: with or without explicit
    # millisecond zeros — both are well-formed ISO 8601.
    cu = data["current_utc"]
    accepted = (
        "2026-12-25T00:00:00.000Z",
        "2026-12-25T00:00:00Z",
    )
    assert cu in accepted, (
        f"SystemClock.current_utc must reflect the value just set, "
        f"got {cu!r} (accepted forms: {accepted})"
    )
